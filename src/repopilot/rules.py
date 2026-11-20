import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

import yaml
from yaml.nodes import MappingNode, Node
from yaml.tokens import AliasToken

from repopilot.adapters.base import ExecutionEvidence, FileListing, RepositoryAdapter
from repopilot.models import Evidence, Finding, Severity, Status


class WorkflowLoader(yaml.SafeLoader):
    # GitHub Actions treats on/off and yes/no as strings.
    yaml_implicit_resolvers = {
        key: [item for item in resolvers if item[0] == "tag:yaml.org,2002:null"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def construct_object(self, node: Node, deep: bool = False) -> object:
        if node.tag not in {
            "tag:yaml.org,2002:map",
            "tag:yaml.org,2002:seq",
            "tag:yaml.org,2002:str",
            "tag:yaml.org,2002:bool",
            "tag:yaml.org,2002:null",
        }:
            raise ValueError("Unsupported YAML tag.")
        try:
            return super().construct_object(node, deep=deep)
        except KeyError:
            raise ValueError("Invalid YAML scalar.") from None

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[object, object]:
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in mapping:
                    raise ValueError("YAML contains a duplicate key.")
                mapping[key] = self.construct_object(value_node, deep=deep)
            except TypeError:
                raise ValueError("YAML contains an invalid mapping key.") from None
        return mapping


WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.IGNORECASE), "tTfF"
)


def load_yaml(text: str) -> object:
    # Alias expansion is unnecessary for these checks. Treat it as unavailable.
    if any(isinstance(token, AliasToken) for token in yaml.scan(text)):
        raise ValueError("YAML aliases are unsupported.")
    return yaml.load(text, Loader=WorkflowLoader)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a YAML mapping with string keys.")
    return cast(dict[str, object], value)


ReadState = Literal["available", "missing", "unknown"]


@dataclass
class RuleContext:
    repository: RepositoryAdapter
    _files: dict[str, tuple[ReadState, str]] = field(default_factory=dict)
    _workflow_paths: list[str] | None = None
    _workflows: tuple[dict[str, dict[str, object]], list[Evidence]] | None = None

    def read(self, path: str) -> tuple[ReadState, str]:
        if path not in self._files:
            try:
                self._files[path] = ("available", self.repository.read_text(path))
            except FileNotFoundError:
                self._files[path] = ("missing", "")
            except (OSError, ValueError):
                self._files[path] = ("unknown", "")
        return self._files[path]

    def workflow_files(self) -> list[str]:
        if self._workflow_paths is not None:
            return self._workflow_paths
        if not isinstance(self.repository, FileListing):
            raise OSError("Workflow inventory is unavailable.")
        paths = [
            path
            for path in self.repository.list_files(".github/workflows")
            if path.endswith((".yml", ".yaml"))
        ]
        if len(paths) > 64:
            raise ValueError("Workflow inventory exceeds the scan limit.")
        self._workflow_paths = paths
        return paths

    def workflows(self) -> tuple[dict[str, dict[str, object]], list[Evidence]]:
        if self._workflows is not None:
            return self._workflows
        found: dict[str, dict[str, object]] = {}
        unreadable: list[Evidence] = []
        try:
            paths = self.workflow_files()
        except (OSError, ValueError):
            paths = []
            unreadable.append(
                Evidence(
                    path=".github/workflows",
                    detail="Workflow inventory is unavailable.",
                )
            )
        for path in paths:
            status, text = self.read(path)
            try:
                if status != "available":
                    raise ValueError
                workflow = _mapping(load_yaml(text))
                _mapping(workflow.get("jobs"))
            except (ValueError, yaml.YAMLError, RecursionError, OverflowError):
                unreadable.append(
                    Evidence(path=path, detail="Workflow could not be read.")
                )
                continue
            found[path] = workflow
        self._workflows = (found, unreadable)
        return self._workflows


RuleResult = tuple[Status, str, list[Evidence]]


class Rule(Protocol):
    @property
    def rule_id(self) -> str: ...

    @property
    def weight(self) -> int: ...

    def evaluate(self, context: RuleContext) -> Finding: ...


@dataclass(frozen=True)
class Check:
    rule_id: str
    severity: Severity
    weight: int
    recommendation: str
    check: Callable[[RuleContext], RuleResult]

    def evaluate(self, context: RuleContext) -> Finding:
        status, message, evidence = self.check(context)
        return Finding(
            rule_id=self.rule_id,
            status=status,
            severity=self.severity,
            message=message,
            recommendation="" if status == "pass" else self.recommendation,
            evidence=evidence,
        )


def _file_check(*paths: str) -> Callable[[RuleContext], RuleResult]:
    def check(context: RuleContext) -> RuleResult:
        evidence = []
        unavailable = False
        for path in paths:
            state, text = context.read(path)
            if state == "available":
                if text.strip():
                    return (
                        "pass",
                        f"Found a nonempty {path}.",
                        [Evidence(path=path, detail="Read nonempty UTF-8 text.")],
                    )
                evidence.append(Evidence(path=path, detail="File is empty."))
            elif state == "unknown":
                unavailable = True
                evidence.append(
                    Evidence(path=path, detail="Could not read file safely.")
                )
        status: Status = "unknown" if unavailable else "fail"
        return status, f"Could not verify a nonempty {paths[0]}.", evidence

    return check


def _configured_ci(context: RuleContext) -> RuleResult:
    try:
        paths = context.workflow_files()
    except (OSError, ValueError):
        return "unknown", "Workflow inventory is unavailable.", []
    if not paths:
        return "fail", "No GitHub Actions workflow files were found.", []
    return (
        "pass",
        "Found GitHub Actions workflow files.",
        [Evidence(path=path, detail="Workflow file is present.") for path in paths],
    )


def _steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for job in _mapping(workflow["jobs"]).values():
        job_steps = _mapping(job).get("steps", [])
        if not isinstance(job_steps, list):
            raise ValueError("Expected a list of steps.")
        steps.extend(_mapping(step) for step in job_steps)
    return steps


_TEST_COMMAND = re.compile(
    r"^\s*(?:(?:uv run|poetry run|python3? -m)\s+)?"
    r"(?:pytest|npm test|npm run test|pnpm test|yarn test|go test|cargo test|"
    r"dotnet test|mvn test|make test|ctest|unittest)(?:\s|$)"
)


def _workflow_checks(
    context: RuleContext,
    inspect: Callable[[dict[str, object]], bool],
    *,
    finding: str,
    clean: str,
    match_status: Literal["pass", "fail"] = "fail",
) -> RuleResult:
    workflows, unavailable = context.workflows()
    evidence = list(unavailable)
    matches = []
    for path, workflow in workflows.items():
        try:
            if inspect(workflow):
                matches.append(Evidence(path=path, detail=finding))
        except ValueError:
            evidence.append(
                Evidence(path=path, detail="Workflow structure is unsupported.")
            )
    if matches:
        return match_status, finding, matches
    if evidence:
        return "unknown", "Workflow evidence is incomplete.", evidence
    if not workflows:
        return "skip", "No workflow files apply.", []
    return (
        ("fail" if match_status == "pass" else "pass"),
        clean,
        [Evidence(path=path, detail=clean) for path in workflows],
    )


def _test_steps(workflow: dict[str, object]) -> bool:
    for step in _steps(workflow):
        command = step.get("run")
        if isinstance(command, str) and any(
            _TEST_COMMAND.match(line) for line in command.splitlines()
        ):
            return True
    return False


def _ci_runs(context: RuleContext) -> RuleResult:
    try:
        if not context.workflow_files():
            return "skip", "No workflow files apply.", []
        if not isinstance(context.repository, ExecutionEvidence):
            return "unknown", "Workflow runs are unavailable in a local scan.", []
        runs = context.repository.workflow_runs()
    except (OSError, ValueError):
        return "unknown", "GitHub workflow runs could not be verified.", []
    failures = {
        "failure",
        "timed_out",
        "cancelled",
        "action_required",
        "startup_failure",
    }
    evidence = (
        [
            Evidence(
                path=".github/workflows", detail=f"{len(runs)} latest runs observed."
            )
        ]
        if runs
        else []
    )
    if any(conclusion in failures for conclusion in runs):
        return "fail", "A latest workflow run did not succeed.", evidence
    if runs and all(conclusion == "success" for conclusion in runs):
        return "pass", "Latest observed workflow runs succeeded.", evidence
    return "unknown", "No conclusive workflow run evidence was found.", evidence


def _permissions(workflow: dict[str, object]) -> bool:
    return workflow.get("permissions") == "write-all" or any(
        _mapping(job).get("permissions") == "write-all"
        for job in _mapping(workflow["jobs"]).values()
    )


_PIN = re.compile(r"^[0-9a-fA-F]{40}$")


def _unpinned(workflow: dict[str, object]) -> bool:
    jobs = [_mapping(job) for job in _mapping(workflow["jobs"]).values()]
    for item in jobs + _steps(workflow):
        uses = item.get("uses")
        if isinstance(uses, str) and not uses.startswith(("./", "docker://")):
            if not _PIN.fullmatch(uses.partition("@")[2]):
                return True
    return False


def _privileged_trigger(workflow: dict[str, object]) -> bool:
    triggers = workflow.get("on")
    if isinstance(triggers, str):
        return triggers == "pull_request_target"
    if isinstance(triggers, (dict, list)):
        return "pull_request_target" in triggers
    if triggers is None:
        return False
    raise ValueError("Unsupported workflow trigger structure.")


def _updates(context: RuleContext) -> RuleResult:
    paths = (
        ".github/dependabot.yml",
        "renovate.json",
        "renovate.jsonc",
        ".github/renovate.json",
        ".github/renovate.jsonc",
        ".renovaterc",
        ".renovaterc.json",
        ".renovaterc.jsonc",
    )
    return _file_check(*paths)(context)


@dataclass(frozen=True)
class RuleRegistry:
    rules: tuple[Rule, ...]

    def evaluate(self, context: RuleContext, disabled: frozenset[str]) -> list[Finding]:
        return [
            rule.evaluate(context)
            for rule in self.rules
            if rule.rule_id not in disabled
        ]


DEFAULT_RULES = RuleRegistry(
    (
        Check(
            "DOC001",
            "low",
            1,
            "Add a readable, nonempty README.md at the repository root.",
            _file_check("README.md", "README.rst", "README"),
        ),
        Check(
            "DOC002",
            "low",
            2,
            "Add a readable, nonempty LICENSE at the repository root.",
            _file_check("LICENSE", "LICENSE.md", "LICENSE.txt"),
        ),
        Check(
            "DOC003",
            "low",
            1,
            "Document how users should contribute.",
            _file_check(
                "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"
            ),
        ),
        Check(
            "DOC004",
            "low",
            1,
            "Publish a security reporting policy.",
            _file_check("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"),
        ),
        Check(
            "SEC001",
            "medium",
            2,
            "Replace write-all with the permissions the job needs.",
            lambda ctx: _workflow_checks(
                ctx,
                _permissions,
                finding="Explicit write-all permissions were found.",
                clean="No explicit write-all permissions were detected.",
            ),
        ),
        Check(
            "SEC002",
            "medium",
            2,
            "Pin remote action references to reviewed commit SHAs.",
            lambda ctx: _workflow_checks(
                ctx,
                _unpinned,
                finding="A remote action uses a mutable reference.",
                clean="No unpinned remote action references were detected.",
            ),
        ),
        Check(
            "SEC003",
            "medium",
            2,
            "Review token permissions for pull_request_target workflows.",
            lambda ctx: _workflow_checks(
                ctx,
                _privileged_trigger,
                finding="A pull_request_target trigger needs review.",
                clean="No pull_request_target triggers were detected.",
            ),
        ),
        Check(
            "CI001",
            "medium",
            2,
            "Add a GitHub Actions workflow for routine checks.",
            _configured_ci,
        ),
        Check(
            "CI002",
            "medium",
            2,
            "Add a recognizable test command to a workflow.",
            lambda ctx: _workflow_checks(
                ctx,
                _test_steps,
                finding="A recognizable test command is configured.",
                clean="No supported test command was detected.",
                match_status="pass",
            ),
        ),
        Check(
            "CI003",
            "medium",
            2,
            "Verify GitHub Actions results for the scanned commit.",
            _ci_runs,
        ),
        Check("MAINT001", "low", 1, "Configure Dependabot or Renovate.", _updates),
        Check(
            "MAINT002",
            "low",
            1,
            "Document code ownership in CODEOWNERS.",
            _file_check(".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"),
        ),
        Check(
            "MAINT003",
            "low",
            1,
            "Add a pull request template.",
            _file_check(
                ".github/PULL_REQUEST_TEMPLATE.md",
                "PULL_REQUEST_TEMPLATE.md",
                "docs/PULL_REQUEST_TEMPLATE.md",
            ),
        ),
        Check(
            "REL001",
            "low",
            1,
            "Document release changes in a changelog.",
            _file_check("CHANGELOG.md", "CHANGELOG.rst", "CHANGELOG"),
        ),
        Check(
            "REL002",
            "low",
            1,
            "Document the release procedure.",
            _file_check("RELEASING.md", "RELEASE.md", "docs/releasing.md"),
        ),
    )
)

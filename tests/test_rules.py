from pathlib import Path

import pytest

from repopilot.adapters.local import LocalRepository
from repopilot.config import ScanConfig, read_config
from repopilot.models import Finding, ScanReport
from repopilot.rules import DEFAULT_RULES, RuleContext
from repopilot.scan import scan_repository
from repopilot.scoring import calculate_score

WORKFLOW = ".github/workflows/ci.yml"
GOOD_WORKFLOW = """on: [push, pull_request]
permissions: read-all
jobs:
  test:
    steps:
      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567
      - run: uv run pytest
"""

FILE_RULES = [
    ("DOC001", "README.md"),
    ("DOC002", "LICENSE"),
    ("DOC003", ".github/CONTRIBUTING.md"),
    ("DOC004", "docs/SECURITY.md"),
    ("MAINT001", ".github/dependabot.yml"),
    ("MAINT002", ".github/CODEOWNERS"),
    ("MAINT003", ".github/PULL_REQUEST_TEMPLATE.md"),
    ("REL001", "CHANGELOG.md"),
    ("REL002", "docs/releasing.md"),
]


def write(root: Path, name: str, data: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def evaluate(root: Path, rule_id: str) -> Finding:
    rule = next(rule for rule in DEFAULT_RULES.rules if rule.rule_id == rule_id)
    return rule.evaluate(RuleContext(LocalRepository(root)))


@pytest.mark.parametrize(("rule_id", "name"), FILE_RULES)
def test_file_rule(tmp_path: Path, rule_id: str, name: str) -> None:
    assert evaluate(tmp_path, rule_id).status == "fail"
    write(tmp_path, name, " ")
    assert evaluate(tmp_path, rule_id).status == "fail"
    write(tmp_path, name, "project information")
    finding = evaluate(tmp_path, rule_id)
    assert finding.status == "pass"
    assert finding.evidence[0].path == name


@pytest.mark.parametrize(
    ("rule_id", "old", "new", "expected"),
    [
        ("SEC001", "read-all", "write-all", "fail"),
        ("SEC002", "0123456789abcdef0123456789abcdef01234567", "v4", "fail"),
        ("SEC003", "pull_request]", "pull_request_target]", "fail"),
        ("CI002", "uv run pytest", "echo pytest", "fail"),
    ],
)
def test_workflow_rule(
    tmp_path: Path, rule_id: str, old: str, new: str, expected: str
) -> None:
    assert evaluate(tmp_path, rule_id).status == "skip"
    write(tmp_path, WORKFLOW, GOOD_WORKFLOW)
    assert evaluate(tmp_path, rule_id).status == "pass"
    write(tmp_path, WORKFLOW, GOOD_WORKFLOW.replace(old, new))
    assert evaluate(tmp_path, rule_id).status == expected
    write(tmp_path, WORKFLOW, "broken: [")
    assert evaluate(tmp_path, rule_id).status == "unknown"


@pytest.mark.parametrize(
    "trigger", ["pull_request_target", "{pull_request_target: {}}"]
)
def test_workflow_trigger_forms(tmp_path: Path, trigger: str) -> None:
    write(tmp_path, WORKFLOW, f"on: {trigger}\njobs: {{}}\n")
    assert evaluate(tmp_path, "SEC003").status == "fail"


def test_ci_config_and_run_evidence(tmp_path: Path) -> None:
    assert evaluate(tmp_path, "CI001").status == "fail"
    assert evaluate(tmp_path, "CI003").status == "skip"
    write(tmp_path, WORKFLOW, GOOD_WORKFLOW)
    assert evaluate(tmp_path, "CI001").status == "pass"
    assert evaluate(tmp_path, "CI003").status == "unknown"


def test_safe_yaml_rejects_unsafe_or_ambiguous_input(tmp_path: Path) -> None:
    for data in (
        "on: push\non: pull_request_target\njobs: {}",
        "on: &x [push, *x]\njobs: {}",
        "!!python/object/apply:os.getcwd []",
        "on: !!bool invalid\njobs: {}",
    ):
        write(tmp_path, WORKFLOW, data)
        assert evaluate(tmp_path, "SEC003").status == "unknown"


def test_weighted_score(tmp_path: Path) -> None:
    write(tmp_path, WORKFLOW, GOOD_WORKFLOW)
    report = scan_repository(LocalRepository(tmp_path))
    ids = [finding.rule_id for finding in report.findings]
    assert len(ids) == len(set(ids)) == 15
    assert report.summary is not None
    assert report.summary.evaluated_weight == 20
    assert report.summary.applicable_weight == 22
    assert report.summary.score == 50
    assert report.summary.coverage == 90.91
    assert scan_repository(LocalRepository(tmp_path)) == report


def test_score_without_evaluated_evidence() -> None:
    finding = Finding(
        rule_id="CI003",
        status="unknown",
        severity="medium",
        message="No evidence",
        recommendation="Check GitHub",
    )
    score = calculate_score([finding], {"CI003": 2})
    assert score.score is None and score.coverage == 0
    empty = calculate_score([], {})
    assert empty.score is None and empty.coverage is None


def test_config_and_old_schema(tmp_path: Path) -> None:
    path = tmp_path / "repopilot.yml"
    path.write_text("rules:\n  DOC001: disabled\n  DOC002: enabled\n")
    report = scan_repository(LocalRepository(tmp_path), read_config(path))
    assert report.findings[0].rule_id == "DOC002"
    with pytest.raises(ValueError, match="unknown rule"):
        scan_repository(
            LocalRepository(tmp_path), ScanConfig(rules={"INVALID": "disabled"})
        )
    old = ScanReport.model_validate_json(
        '{"schema_version":"1.0","repository":"example","is_git_repository":false}'
    )
    assert old.summary is None

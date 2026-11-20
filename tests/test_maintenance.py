from pathlib import Path

import pytest
from typer.testing import CliRunner

from repopilot.cli import app
from repopilot.maintenance import (
    RELEASE_RULES,
    build_plan,
    check_release,
    compare_scans,
)
from repopilot.markdown import plan_markdown
from repopilot.models import (
    Evidence,
    Finding,
    MaintenancePlan,
    ReleaseReport,
    ScanDiff,
    ScanReport,
    Severity,
    Status,
)

RUNNER = CliRunner()


def finding(
    rule: str,
    status: Status,
    *,
    resource: str = "repository",
    severity: Severity = "medium",
    evidence: bool = False,
) -> Finding:
    return Finding(
        rule_id=rule,
        status=status,
        resource=resource,
        severity=severity,
        message="Observed evidence",
        recommendation="Review the finding.",
        evidence=[Evidence(path="ci.yml", detail="Workflow state")] if evidence else [],
    )


def scan_report(*findings: Finding) -> ScanReport:
    return ScanReport(
        repository="fixture", is_git_repository=True, findings=list(findings)
    )


def test_plan_is_deterministic_with_prerequisites() -> None:
    findings = [
        finding("CI003", "fail", evidence=True),
        finding("DOC001", "fail", severity="low"),
        finding("CI002", "fail", evidence=True),
        finding("SEC001", "unknown"),
        finding("CI001", "fail"),
        finding("SEC002", "fail", severity="high"),
    ]
    result = build_plan(scan_report(*findings))
    assert result == build_plan(scan_report(*reversed(findings)))
    assert [task.rule_id for task in result.tasks] == [
        "SEC002",
        "CI001",
        "CI002",
        "CI003",
        "DOC001",
    ]
    assert result.tasks[3].depends_on == ["CI001", "CI002"]
    assert all(task.acceptance_criteria for task in result.tasks)


def test_diff_matches_rule_and_resource() -> None:
    baseline = scan_report(
        finding("DOC001", "fail", resource="service-a"),
        finding("DOC001", "fail", resource="service-b"),
        finding("CI001", "fail"),
        finding("SEC001", "fail"),
    )
    current = scan_report(
        finding("DOC001", "fail", resource="service-b", evidence=True),
        finding("SEC001", "unknown"),
        finding("DOC002", "fail"),
        finding("DOC001", "pass", resource="service-a"),
    )
    result = compare_scans(baseline, current)
    assert [item.finding.rule_id for item in result.added] == ["DOC002"]
    assert [item.finding.resource for item in result.resolved] == ["service-a"]
    assert [item.finding.resource for item in result.persistent] == ["service-b"]
    assert [(item.finding.rule_id, item.after) for item in result.unverified] == [
        ("CI001", None),
        ("SEC001", "unknown"),
    ]


def test_duplicate_finding_identity_is_rejected() -> None:
    repeated = finding("CI001", "fail")
    with pytest.raises(ValueError, match="duplicate"):
        build_plan(scan_report(repeated, repeated))


def test_release_requires_verified_checks() -> None:
    passed = [finding(rule, "pass") for rule in RELEASE_RULES]
    assert check_release(scan_report(*passed)).readiness == "ready"
    assert check_release(scan_report(*passed[:-1])).readiness == "incomplete"
    assert check_release(
        scan_report(*passed[:-1], finding("REL002", "skip"))
    ).readiness == ("incomplete")
    assert check_release(scan_report(finding("CI003", "fail"))).readiness == "blocked"


def test_markdown_does_not_activate_report_markup() -> None:
    item = finding("CI001", "fail")
    item.recommendation = "# Injected\n<img src=x> [link](https://example.org)"
    result = plan_markdown(build_plan(scan_report(item)))
    assert "\\# Injected" in result
    assert r"\<img src\=x\>" in result
    assert "[link](" not in result


def test_scan_plan_and_diff_cli(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    readme = target / "README.md"
    readme.write_text("# Example", encoding="utf-8")
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    plan_file = tmp_path / "plan.md"
    assert RUNNER.invoke(app, ["scan", str(target), "-o", str(before)]).exit_code == 0
    plan_result = RUNNER.invoke(app, ["plan", str(before), "--format", "json"])
    assert plan_result.exit_code == 0, plan_result.output
    tasks = MaintenancePlan.model_validate_json(plan_result.stdout).tasks
    assert "DOC002" in {task.rule_id for task in tasks}
    assert "DOC001" not in {task.rule_id for task in tasks}
    assert (
        RUNNER.invoke(app, ["plan", str(before), "-o", str(plan_file)]).exit_code == 0
    )
    assert "# Maintenance plan" in plan_file.read_text(encoding="utf-8")

    readme.unlink()
    (target / "LICENSE").write_text("License", encoding="utf-8")
    assert RUNNER.invoke(app, ["scan", str(target), "-o", str(after)]).exit_code == 0
    result = RUNNER.invoke(app, ["diff", str(before), str(after), "--format", "json"])
    assert result.exit_code == 0, result.output
    diff = ScanDiff.model_validate_json(result.stdout)
    assert [change.finding.rule_id for change in diff.added] == ["DOC001"]
    assert [change.finding.rule_id for change in diff.resolved] == ["DOC002"]
    assert diff.persistent

    markdown = RUNNER.invoke(app, ["scan", str(target), "--format", "markdown"])
    assert markdown.exit_code == 0
    assert "# Repository scan" in markdown.stdout


def test_release_check_cli(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["release-check", str(tmp_path), "--format", "json"])
    assert result.exit_code == 1
    status = ReleaseReport.model_validate_json(result.stdout)
    assert status.readiness == "blocked"
    assert any(check.status == "unknown" for check in status.checks)

    for name in ("README.md", "LICENSE", "CHANGELOG.md", "RELEASING.md"):
        (tmp_path / name).write_text("Evidence", encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "on: push\njobs: {test: {steps: [{run: pytest}]}}\n", encoding="utf-8"
    )
    result = RUNNER.invoke(app, ["release-check", str(tmp_path)])
    assert result.exit_code == 1
    assert "Readiness: incomplete" in result.stdout
    assert "CI003" in result.stdout


def test_bad_schema_and_overwriting_input_return_two(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text('{"schema_version":"2.0"}', encoding="utf-8")
    bad = RUNNER.invoke(app, ["plan", str(path)])
    assert bad.exit_code == 2 and "schema version" in bad.stderr

    original = scan_report(finding("DOC001", "fail")).model_dump_json()
    path.write_text(original, encoding="utf-8")
    collision = RUNNER.invoke(app, ["plan", str(path), "-o", str(path)])
    assert collision.exit_code == 2
    assert path.read_text(encoding="utf-8") == original

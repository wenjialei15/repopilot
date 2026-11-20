import re
from unicodedata import category

from repopilot.models import (
    Evidence,
    Finding,
    FindingChange,
    MaintenancePlan,
    ReleaseReport,
    ScanDiff,
    ScanReport,
)

_MARKUP = re.compile(r"([!\x22#$%&'()*+,./:;<=>?@\[\]\\^`_{|}~\-])")


def _plain(value: str) -> str:
    value = " ".join(value.split())
    value = "".join(char for char in value if not category(char).startswith("C"))
    return _MARKUP.sub(r"\\\1", value)


def _evidence(evidence: list[Evidence]) -> list[str]:
    return [
        f"- Evidence at {_plain(item.path)}. {_plain(item.detail)}" for item in evidence
    ]


def _label(finding: Finding) -> str:
    label = _plain(finding.rule_id)
    if finding.resource != "repository":
        label += f" · {_plain(finding.resource)}"
    return label


def _findings(findings: list[Finding]) -> list[str]:
    lines = []
    for finding in findings:
        lines += [
            "",
            f"### {_label(finding)} · {finding.status}",
            "",
            _plain(finding.message),
        ]
        lines.extend(_evidence(finding.evidence))
        if finding.recommendation:
            lines.append(f"- Action: {_plain(finding.recommendation)}")
    return lines


def scan_markdown(report: ScanReport) -> str:
    lines = ["# Repository scan", "", f"Repository: {_plain(report.repository)}"]
    if report.summary:
        score = report.summary.score
        coverage = report.summary.coverage
        score_text = f"{score:g}/100" if score is not None else "Unavailable"
        coverage_text = f"{coverage:g}%" if coverage is not None else "Unavailable"
        lines.extend(
            [
                "",
                f"- Health score: {score_text}",
                f"- Evidence coverage: {coverage_text}",
            ]
        )
    return "\n".join(lines + _findings(report.findings))


def plan_markdown(plan: MaintenancePlan) -> str:
    lines = ["# Maintenance plan", "", f"Repository: {_plain(plan.repository)}"]
    if not plan.tasks:
        return "\n".join([*lines, "", "No failed rules were found in the report."])
    for task in plan.tasks:
        label = _plain(task.rule_id)
        if task.resource != "repository":
            label += f" · {_plain(task.resource)}"
        lines.extend(
            [
                "",
                f"## {label} · {_plain(task.title)}",
                "",
                f"- Severity: {task.severity}",
                f"- Estimated effort: {task.effort}",
            ]
        )
        lines.extend(_evidence(task.evidence))
        if task.depends_on:
            prerequisites = ", ".join(_plain(rule) for rule in task.depends_on)
            lines.append(f"- Depends on: {prerequisites}")
        lines.extend(
            f"- Acceptance: {_plain(item)}" for item in task.acceptance_criteria
        )
    return "\n".join(lines)


def _changes(title: str, changes: list[FindingChange]) -> list[str]:
    lines = ["", f"## {title} ({len(changes)})", ""]
    lines.extend(
        f"- {_label(change.finding)} ({change.before or 'absent'} → "
        f"{change.after or 'absent'}). {_plain(change.finding.message)}"
        for change in changes
    )
    if not changes:
        lines.append("None.")
    return lines


def diff_markdown(diff: ScanDiff) -> str:
    lines = [
        "# Scan comparison",
        "",
        f"Baseline: {_plain(diff.baseline_repository)}",
        f"Current: {_plain(diff.current_repository)}",
    ]
    for title, changes in (
        ("Added", diff.added),
        ("Resolved", diff.resolved),
        ("Persistent", diff.persistent),
        ("Unverified", diff.unverified),
    ):
        lines.extend(_changes(title, changes))
    return "\n".join(lines)


def release_markdown(report: ReleaseReport) -> str:
    lines = [
        "# Release readiness",
        "",
        f"Repository: {_plain(report.repository)}",
        f"Readiness: {report.readiness}",
    ]
    return "\n".join(lines + _findings(report.checks))

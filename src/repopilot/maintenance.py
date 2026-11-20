from repopilot.models import (
    Finding,
    FindingChange,
    MaintenancePlan,
    PlanTask,
    ReleaseReport,
    ScanDiff,
    ScanReport,
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
EFFORT_ORDER = {"small": 0, "medium": 1, "unknown": 2}
RELEASE_RULES = ("DOC001", "DOC002", "CI001", "CI002", "CI003", "REL001", "REL002")
RULE_DEPENDENCIES = {"CI002": ("CI001",), "CI003": ("CI001", "CI002")}
SMALL_TASKS = {
    "DOC001",
    "DOC002",
    "DOC003",
    "DOC004",
    "SEC001",
    "SEC002",
    "MAINT002",
    "MAINT003",
    "REL001",
}
MEDIUM_TASKS = {"SEC003", "CI001", "CI002", "CI003", "MAINT001", "REL002"}


def _findings_by_identity(report: ScanReport) -> dict[tuple[str, str], Finding]:
    result: dict[tuple[str, str], Finding] = {}
    for finding in report.findings:
        key = (finding.rule_id, finding.resource)
        if key in result:
            raise ValueError("Report contains duplicate rule and resource identifiers.")
        result[key] = finding
    return result


def _priority(task: PlanTask) -> tuple[int, bool, int, str, str]:
    return (
        SEVERITY_ORDER[task.severity],
        not task.evidence,
        EFFORT_ORDER[task.effort],
        task.rule_id,
        task.resource,
    )


def build_plan(report: ScanReport) -> MaintenancePlan:
    findings = _findings_by_identity(report)
    tasks: dict[tuple[str, str], PlanTask] = {}
    for key, finding in findings.items():
        if finding.status != "fail":
            continue
        prerequisites = [
            rule
            for rule in RULE_DEPENDENCIES.get(finding.rule_id, ())
            if (rule, finding.resource) in findings
            and findings[(rule, finding.resource)].status == "fail"
        ]
        task = PlanTask(
            rule_id=finding.rule_id,
            resource=finding.resource,
            title=finding.recommendation or finding.message,
            severity=finding.severity,
            evidence=finding.evidence,
            depends_on=prerequisites,
            acceptance_criteria=[
                "Rescan with the same scope and confirm "
                f"{finding.rule_id} reports pass."
            ],
        )
        if finding.rule_id in SMALL_TASKS:
            task.effort = "small"
        elif finding.rule_id in MEDIUM_TASKS:
            task.effort = "medium"
        tasks[key] = task

    ordered: list[PlanTask] = []
    emitted: set[tuple[str, str]] = set()

    def append_task(task: PlanTask) -> None:
        key = (task.rule_id, task.resource)
        if key in emitted:
            return
        for rule in task.depends_on:
            append_task(tasks[(rule, task.resource)])
        ordered.append(task)
        emitted.add(key)

    for task in sorted(tasks.values(), key=_priority):
        append_task(task)
    return MaintenancePlan(repository=report.repository, tasks=ordered)


def compare_scans(baseline: ScanReport, current: ScanReport) -> ScanDiff:
    earlier = _findings_by_identity(baseline)
    later = _findings_by_identity(current)
    result = ScanDiff(
        baseline_repository=baseline.repository,
        current_repository=current.repository,
        added=[],
        resolved=[],
        persistent=[],
        unverified=[],
    )
    for key in sorted(earlier.keys() | later.keys()):
        old, new = earlier.get(key), later.get(key)
        if new is not None and new.status == "fail":
            change = FindingChange(
                finding=new, before=old.status if old else None, after="fail"
            )
            (
                result.persistent if old and old.status == "fail" else result.added
            ).append(change)
        elif old is not None and old.status == "fail":
            change = FindingChange(
                finding=new if new is not None else old,
                before="fail",
                after=new.status if new else None,
            )
            (result.resolved if change.after == "pass" else result.unverified).append(
                change
            )
    return result


def check_release(report: ScanReport) -> ReleaseReport:
    findings = _findings_by_identity(report)
    checks = []
    for rule in RELEASE_RULES:
        finding = findings.get((rule, "repository"))
        if finding is None or finding.status == "skip":
            finding = Finding(
                rule_id=rule,
                status="unknown",
                severity=finding.severity if finding else "medium",
                message=finding.message
                if finding
                else "Required release evidence is missing.",
                recommendation="Supply observable evidence for this release check.",
                evidence=finding.evidence if finding else [],
            )
        checks.append(finding)
    if any(finding.status == "fail" for finding in checks):
        return ReleaseReport(
            repository=report.repository, readiness="blocked", checks=checks
        )
    if any(finding.status == "unknown" for finding in checks):
        return ReleaseReport(
            repository=report.repository, readiness="incomplete", checks=checks
        )
    return ReleaseReport(repository=report.repository, readiness="ready", checks=checks)

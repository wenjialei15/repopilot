from unicodedata import category

from rich.console import Console
from rich.table import Table
from rich.text import Text

from repopilot.models import ScanReport


def _safe_text(value: str) -> str:
    return "".join(char for char in value if not category(char).startswith("C"))


def print_terminal(report: ScanReport) -> None:
    console = Console()
    console.print(Text(_safe_text(report.repository), style="bold"))
    if report.summary:
        score = (
            "unavailable"
            if report.summary.score is None
            else f"{report.summary.score:g}/100"
        )
        coverage = (
            "unavailable"
            if report.summary.coverage is None
            else f"{report.summary.coverage:g}%"
        )
        console.print(f"Score {score} | Evidence coverage {coverage}")
    table = Table("Rule", "Status", "Finding", "Evidence", "Recommended action")
    for finding in report.findings:
        evidence = "\n".join(
            f"{_safe_text(item.path)}: {item.detail}" for item in finding.evidence
        )
        table.add_row(
            finding.rule_id,
            finding.status,
            Text(finding.message),
            Text(evidence),
            Text(finding.recommendation),
        )
    console.print(table)

from enum import StrEnum
from importlib.metadata import version
from os import getenv
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from repopilot import DISTRIBUTION_NAME
from repopilot.adapters.github import GitHubError, GitHubRepository, github_client
from repopilot.adapters.local import LocalRepository
from repopilot.config import ScanConfig, read_config
from repopilot.maintenance import build_plan, check_release, compare_scans
from repopilot.markdown import (
    diff_markdown,
    plan_markdown,
    release_markdown,
    scan_markdown,
)
from repopilot.models import ScanReport
from repopilot.report_files import read_report, write_report
from repopilot.reporting import print_terminal
from repopilot.scan import scan_repository

app = typer.Typer(help="Run read-only repository health checks.", no_args_is_help=True)


class OutputFormat(StrEnum):
    JSON = "json"
    TERMINAL = "terminal"
    MARKDOWN = "markdown"


class WorkflowFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"


Target = Annotated[str, typer.Argument(help="Local directory or github:owner/repo.")]
Destination = Annotated[Path | None, typer.Option("--output", "-o")]
DocumentFormat = Annotated[WorkflowFormat, typer.Option("--format")]


def _scan_target(path: str, config: ScanConfig | None = None) -> ScanReport:
    try:
        if path.startswith("github:"):
            with github_client(getenv("GITHUB_TOKEN")) as client:
                return scan_repository(GitHubRepository(client, path), config)
        return scan_repository(LocalRepository(Path(path)), config)
    except (GitHubError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from None
    except (OSError, RuntimeError):
        typer.echo("Error: scan target must be an accessible directory.", err=True)
        raise typer.Exit(2) from None


def _input_report(path: Path) -> ScanReport:
    try:
        return read_report(path)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from None
    except OSError:
        typer.echo("Error: could not read the scan report.", err=True)
        raise typer.Exit(2) from None


def _emit(body: str, output: Path | None, *, inputs: tuple[Path, ...] = ()) -> None:
    if output is None:
        typer.echo(body)
        return
    try:
        write_report(output, body, inputs=inputs)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from None
    except (OSError, RuntimeError):
        typer.echo("Error: could not write the report.", err=True)
        raise typer.Exit(2) from None


def _document(
    report: BaseModel,
    markdown: str,
    output_format: WorkflowFormat,
    output: Path | None,
    *,
    inputs: tuple[Path, ...] = (),
) -> None:
    body = (
        report.model_dump_json(indent=2)
        if output_format is WorkflowFormat.JSON
        else markdown
    )
    _emit(body, output, inputs=inputs)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"RepoPilot {version(DISTRIBUTION_NAME)}")
        raise typer.Exit()


@app.callback()
def main(
    show_version: Annotated[
        bool, typer.Option("--version", callback=_show_version, is_eager=True)
    ] = False,
) -> None:
    """Inspect repository maintenance evidence."""


@app.command()
def scan(
    path: Target = ".",
    output_format: Annotated[
        OutputFormat, typer.Option("--format")
    ] = OutputFormat.JSON,
    config_path: Annotated[Path | None, typer.Option("--config")] = None,
    output: Destination = None,
) -> None:
    """Check a local directory or public GitHub repository."""
    try:
        config = read_config(config_path) if config_path else ScanConfig()
    except (OSError, ValueError):
        typer.echo("Error: could not read a valid scan configuration.", err=True)
        raise typer.Exit(2) from None

    if output is not None and output_format is OutputFormat.TERMINAL:
        typer.echo("Error: --output requires JSON or Markdown.", err=True)
        raise typer.Exit(2)
    report = _scan_target(path, config)
    if output_format is OutputFormat.TERMINAL:
        print_terminal(report)
    else:
        body = (
            scan_markdown(report)
            if output_format is OutputFormat.MARKDOWN
            else report.model_dump_json(indent=2)
        )
        _emit(body, output, inputs=(config_path,) if config_path else ())


@app.command()
def plan(
    report_path: Annotated[Path, typer.Argument(help="JSON scan report.")],
    output_format: DocumentFormat = WorkflowFormat.MARKDOWN,
    output: Destination = None,
) -> None:
    """Generate a prioritized maintenance plan from failed checks."""
    try:
        report = build_plan(_input_report(report_path))
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from None
    _document(
        report, plan_markdown(report), output_format, output, inputs=(report_path,)
    )


@app.command()
def diff(
    baseline: Annotated[Path, typer.Argument(help="Baseline JSON scan report.")],
    current: Annotated[Path, typer.Argument(help="Current JSON scan report.")],
    output_format: DocumentFormat = WorkflowFormat.MARKDOWN,
    output: Destination = None,
) -> None:
    """Compare failed checks between two scans."""
    try:
        report = compare_scans(_input_report(baseline), _input_report(current))
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from None
    _document(
        report, diff_markdown(report), output_format, output, inputs=(baseline, current)
    )


@app.command()
def release_check(
    path: Target = ".",
    output_format: DocumentFormat = WorkflowFormat.MARKDOWN,
    output: Destination = None,
) -> None:
    """Check whether the required release evidence is available and passing."""
    report = check_release(_scan_target(path))
    _document(report, release_markdown(report), output_format, output)
    if report.readiness != "ready":
        raise typer.Exit(1)

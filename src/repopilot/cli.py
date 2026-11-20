from enum import StrEnum
from importlib.metadata import version
from os import getenv
from pathlib import Path
from typing import Annotated

import typer

from repopilot.adapters.github import GitHubError, GitHubRepository, github_client
from repopilot.adapters.local import LocalRepository
from repopilot.config import ScanConfig, read_config
from repopilot.reporting import print_terminal
from repopilot.scan import scan_repository

app = typer.Typer(help="Run read-only repository health checks.", no_args_is_help=True)


class OutputFormat(StrEnum):
    JSON = "json"
    TERMINAL = "terminal"


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"RepoPilot {version('repopilot')}")
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
    path: Annotated[
        str, typer.Argument(help="Local directory or github:owner/repo.")
    ] = ".",
    output_format: Annotated[
        OutputFormat, typer.Option("--format")
    ] = OutputFormat.JSON,
    config_path: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Check a local directory or public GitHub repository."""
    try:
        config = read_config(config_path) if config_path else ScanConfig()
    except (OSError, ValueError):
        typer.echo("Error: could not read a valid scan configuration.", err=True)
        raise typer.Exit(2) from None

    try:
        if path.startswith("github:"):
            with github_client(getenv("GITHUB_TOKEN")) as client:
                report = scan_repository(GitHubRepository(client, path), config)
        else:
            report = scan_repository(LocalRepository(Path(path)), config)
    except (GitHubError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(2) from None
    except (OSError, RuntimeError):
        typer.echo("Error: scan target must be an accessible directory.", err=True)
        raise typer.Exit(2) from None

    if output_format is OutputFormat.TERMINAL:
        print_terminal(report)
    else:
        typer.echo(report.model_dump_json(indent=2))

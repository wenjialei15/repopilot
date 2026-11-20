from pathlib import Path

import pytest
from typer.testing import CliRunner

from repopilot.adapters.local import MAX_FILE_BYTES, LocalRepository
from repopilot.cli import app
from repopilot.models import ScanReport

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("fixture", "statuses"),
    [
        ("healthy", ["pass", "pass"]),
        ("incomplete", ["pass", "fail"]),
        ("empty", ["fail", "fail"]),
    ],
)
def test_scan_reports_valid_json(fixture: str, statuses: list[str]) -> None:
    result = CliRunner().invoke(app, ["scan", str(FIXTURES / fixture)])
    assert result.exit_code == 0
    report = ScanReport.model_validate_json(result.stdout)
    assert report.schema_version == "1.0"
    assert not report.is_git_repository
    assert [finding.status for finding in report.findings[:2]] == statuses
    assert len(report.findings) == 15


@pytest.mark.parametrize("marker_is_directory", [True, False])
def test_git_marker(tmp_path: Path, marker_is_directory: bool) -> None:
    marker = tmp_path / ".git"
    if marker_is_directory:
        marker.mkdir()
    else:
        marker.write_text("gitdir: ../worktree", encoding="utf-8")
    assert LocalRepository(tmp_path).is_git_repository


@pytest.mark.parametrize(
    "path", ["../outside", "C:secret", "docs\\..\\secret", "/etc/passwd"]
)
def test_rejects_path_escape(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        LocalRepository(tmp_path).read_text(path)


def test_refuses_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("fixture", encoding="utf-8")
    try:
        (tmp_path / "README.md").symlink_to(target)
    except OSError:
        pytest.skip("Symlinks are unavailable to this account.")
    with pytest.raises(ValueError, match="links"):
        LocalRepository(tmp_path).read_text("README.md")


@pytest.mark.parametrize("content", [b"x" * (MAX_FILE_BYTES + 1), b"\xff"])
def test_unreadable_findings_are_unknown(tmp_path: Path, content: bytes) -> None:
    (tmp_path / "README.md").write_bytes(content)
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    report = ScanReport.model_validate_json(result.stdout)
    assert report.findings[0].status == "unknown"


def test_rejects_non_directory(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["scan", str(tmp_path / "missing")])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "accessible directory" in result.stderr


@pytest.mark.parametrize("option", ["--help", "--version"])
def test_cli_options(option: str) -> None:
    result = CliRunner().invoke(app, [option], prog_name="repopilot")
    assert result.exit_code == 0
    assert "repopilot" in result.stdout.lower()


def test_terminal_report() -> None:
    result = CliRunner().invoke(
        app,
        ["scan", str(FIXTURES / "incomplete"), "--format", "terminal"],
        env={"COLUMNS": "160"},
    )
    assert result.exit_code == 0
    assert "Evidence coverage" in result.stdout
    assert "DOC002" in result.stdout
    assert "Add a readable" in result.stdout


def test_invalid_explicit_config(tmp_path: Path) -> None:
    config = tmp_path / "repopilot.yml"
    config.write_text("rules: [DOC001]", encoding="utf-8")
    result = CliRunner().invoke(app, ["scan", str(tmp_path), "--config", str(config)])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "configuration" in result.stderr

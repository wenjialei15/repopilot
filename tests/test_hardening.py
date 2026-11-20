import os
import runpy
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repopilot.adapters.local import LocalRepository
from repopilot.cli import app
from repopilot.config import read_config
from repopilot.report_files import read_report
from repopilot.rules import load_yaml
from repopilot.scan import scan_repository


@pytest.mark.parametrize(
    "path", ["//server/share", "README.md:stream", "nested/NUL.txt", "dir./README.md"]
)
def test_adapter_rejects_nonportable_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        LocalRepository(tmp_path).read_text(path)


def test_replaced_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    repository = LocalRepository(root)
    root.rename(tmp_path / "original")
    root.mkdir()
    (root / "README.md").write_text("Replacement", encoding="utf-8")
    with pytest.raises(ValueError, match="root changed"):
        repository.read_text("README.md")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX special file required")
def test_special_inputs_are_rejected(tmp_path: Path) -> None:
    pipe = tmp_path / "README.md"
    os.mkfifo(pipe)
    for read in (read_config, read_report):
        with pytest.raises(ValueError, match="regular file"):
            read(pipe)
    with pytest.raises(ValueError, match="regular file"):
        LocalRepository(tmp_path).read_text("README.md")


@pytest.mark.parametrize("source", ["[" * 80 + "]" * 80, "[" + "x," * 12_000 + "]"])
def test_yaml_structural_limits(source: str) -> None:
    with pytest.raises(ValueError, match="structural"):
        load_yaml(source)


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":"1.0","schema_version":"2.0"}',
        '{"schema_version":"1.0","more":NaN}',
        '{"schema_version":"1.0","repository":"\\ud800","is_git_repository":false,"findings":[]}',
    ],
)
def test_unusable_report_data(tmp_path: Path, payload: str) -> None:
    report = tmp_path / "report.json"
    report.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="report"):
        read_report(report)


def test_concurrent_scans_keep_evidence_separate(tmp_path: Path) -> None:
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "README.md").write_text("Left fixture", encoding="utf-8")
    (right / "LICENSE").write_text("Right fixture", encoding="utf-8")

    def scan(path: Path) -> tuple[str, str]:
        readme, license_file = scan_repository(LocalRepository(path)).findings[:2]
        return readme.status, license_file.status

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert (
            list(workers.map(scan, [left, right] * 4))
            == [("pass", "fail"), ("fail", "pass")] * 4
        )


def test_cli_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["repopilot", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("repopilot", run_name="__main__", alter_sys=True)
    assert exit_info.value.code == 0


def test_cli_file_errors_preserve_output_destination(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = runner.invoke(app, ["plan", str(tmp_path / "missing.json")])
    assert missing.exit_code == 2 and "could not read" in missing.stderr
    output = runner.invoke(app, ["scan", str(tmp_path), "-o", str(tmp_path)])
    assert output.exit_code == 2 and "could not write" in output.stderr
    assert tmp_path.is_dir()

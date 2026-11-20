import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError

from repopilot.fileio import read_regular_file
from repopilot.models import ScanReport

MAX_REPORT_BYTES = 4 * 1024 * 1024


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("Expected a finite JSON value.")


def read_report(path: Path) -> ScanReport:
    data = read_regular_file(path, MAX_REPORT_BYTES)
    try:
        payload = json.loads(
            data, object_pairs_hook=_unique_keys, parse_constant=_reject_constant
        )
    except (ValueError, RecursionError):
        raise ValueError("Scan report is not valid JSON.") from None
    if not isinstance(payload, dict) or "schema_version" not in payload:
        raise ValueError("Scan report is missing its schema version.")
    if payload["schema_version"] != "1.0":
        raise ValueError("Unsupported scan report schema version. Expected 1.0.")
    if (
        not {"schema_version", "repository", "is_git_repository", "findings"}
        <= payload.keys()
    ):
        raise ValueError("Scan report is missing required fields.")
    try:
        return ScanReport.model_validate_json(json.dumps(payload, allow_nan=False))
    except (ValueError, ValidationError, RecursionError):
        raise ValueError("Scan report does not match schema 1.0.") from None


def write_report(path: Path, body: str, *, inputs: tuple[Path, ...] = ()) -> None:
    if any(path.resolve() == source.resolve() for source in inputs):
        raise ValueError("Output must be a different file from the input report.")
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(body.rstrip("\n") + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

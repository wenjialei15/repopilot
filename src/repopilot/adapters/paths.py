import ntpath
from collections.abc import Callable
from pathlib import PureWindowsPath

MAX_FILE_BYTES = 256 * 1024
_WINDOWS_IS_RESERVED: Callable[[str], bool] | None = getattr(ntpath, "isreserved", None)


def _reserved_windows_name(part: str) -> bool:
    if _WINDOWS_IS_RESERVED is not None:
        return _WINDOWS_IS_RESERVED(part)
    return PureWindowsPath(part).is_reserved()


def path_parts(path: str) -> list[str]:
    parts = path.split("/")
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((" ", "."))
        or any(char in part for char in "\\:\x00")
        or _reserved_windows_name(part)
        for part in parts
    ):
        raise ValueError("Expected a repository-relative path.")
    return parts

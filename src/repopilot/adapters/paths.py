from pathlib import PureWindowsPath

MAX_FILE_BYTES = 256 * 1024


def path_parts(path: str) -> list[str]:
    parts = path.split("/")
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((" ", "."))
        or any(char in part for char in "\\:\x00")
        or PureWindowsPath(part).is_reserved()
        for part in parts
    ):
        raise ValueError("Expected a repository-relative path.")
    return parts

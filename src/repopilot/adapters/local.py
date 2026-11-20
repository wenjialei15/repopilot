import os
import stat
from pathlib import Path

from repopilot.adapters.paths import MAX_FILE_BYTES as MAX_FILE_BYTES
from repopilot.adapters.paths import path_parts


class LocalRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError("Scan target must be a directory.")

    @property
    def name(self) -> str:
        return self.root.name or self.root.anchor

    @property
    def is_git_repository(self) -> bool:
        try:
            marker = self._checked_path(".git")
            mode = marker.lstat().st_mode
        except (OSError, ValueError):
            return False
        return stat.S_ISDIR(mode) or stat.S_ISREG(mode)

    def _checked_path(self, relative_path: str) -> Path:
        candidate = self.root
        for part in path_parts(relative_path):
            candidate /= part
            metadata = candidate.lstat()
            attributes = getattr(metadata, "st_file_attributes", 0)
            is_reparse_point = bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            if stat.S_ISLNK(metadata.st_mode) or is_reparse_point:
                raise ValueError("Repository links and reparse points are unsupported.")
        if not candidate.resolve(strict=True).is_relative_to(self.root):
            raise ValueError("Path escapes the scan root.")
        return candidate

    def list_files(self, relative_directory: str) -> list[str]:
        try:
            directory = self._checked_path(relative_directory)
        except FileNotFoundError:
            return []
        found = []
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= 2_000:
                    raise ValueError("Directory exceeds the scan listing limit.")
                if not entry.is_dir(follow_symlinks=False):
                    found.append(f"{relative_directory}/{entry.name}")
        return sorted(found)

    def read_text(self, relative_path: str) -> str:
        path = self._checked_path(relative_path)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Expected a regular file.")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
                metadata, opened
            ):
                raise ValueError("File changed while opening.")
            if not os.path.samestat(self._checked_path(relative_path).lstat(), opened):
                raise ValueError("Path changed while opening.")
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("File exceeds the scan size limit.")
        return data.decode("utf-8-sig")

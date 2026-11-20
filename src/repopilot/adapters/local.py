import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from repopilot.adapters.paths import MAX_FILE_BYTES as MAX_FILE_BYTES
from repopilot.adapters.paths import path_parts
from repopilot.fileio import READ_FLAGS, read_descriptor

_DIRECTORY_LIMIT = 2_000
_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY: int = getattr(os, "O_DIRECTORY", 0)
_DESCRIPTOR_PATHS = (
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.scandir in os.supports_fd
    and bool(_DIRECTORY)
    and bool(_NOFOLLOW)
)


def _reject_links(metadata: os.stat_result) -> None:
    attributes = getattr(metadata, "st_file_attributes", 0)
    if stat.S_ISLNK(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("Repository links and reparse points are unsupported.")


def _listed_files(directory: Path | int, relative_directory: str) -> list[str]:
    found = []
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= _DIRECTORY_LIMIT:
                raise ValueError("Directory exceeds the scan listing limit.")
            if not entry.is_dir(follow_symlinks=False):
                found.append(f"{relative_directory}/{entry.name}")
    return sorted(found)


class LocalRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self._root_stat = self.root.lstat()
        _reject_links(self._root_stat)
        if not stat.S_ISDIR(self._root_stat.st_mode):
            raise NotADirectoryError("Scan target must be a directory.")

    @property
    def name(self) -> str:
        return self.root.name or self.root.anchor

    @property
    def is_git_repository(self) -> bool:
        try:
            marker = self._checked_path([".git"])
            mode = marker.lstat().st_mode
        except (OSError, ValueError, RuntimeError):
            return False
        return stat.S_ISDIR(mode) or stat.S_ISREG(mode)

    @contextmanager
    def _open_directory(self, parts: list[str]) -> Iterator[int]:
        flags = READ_FLAGS | _DIRECTORY | _NOFOLLOW
        descriptor = os.open(self.root, flags)
        try:
            if not os.path.samestat(self._root_stat, os.fstat(descriptor)):
                raise ValueError("Scan root changed during the scan.")
            for part in parts:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor
        finally:
            os.close(descriptor)

    def _checked_path(self, parts: list[str]) -> Path:
        root_metadata = self.root.lstat()
        _reject_links(root_metadata)
        if not os.path.samestat(self._root_stat, root_metadata):
            raise ValueError("Scan root changed during the scan.")
        candidate = self.root
        for part in parts:
            candidate /= part
            _reject_links(candidate.lstat())
        if not candidate.resolve(strict=True).is_relative_to(self.root):
            raise ValueError("Path escapes the scan root.")
        return candidate

    def list_files(self, relative_directory: str) -> list[str]:
        parts = path_parts(relative_directory)
        try:
            if _DESCRIPTOR_PATHS:
                with self._open_directory(parts) as descriptor:
                    return _listed_files(descriptor, relative_directory)
            directory = self._checked_path(parts)
            metadata = directory.lstat()
            _reject_links(metadata)
            found = _listed_files(directory, relative_directory)
            if not os.path.samestat(metadata, self._checked_path(parts).lstat()):
                raise ValueError("Directory changed while listing.")
            return found
        except FileNotFoundError:
            return []

    def read_text(self, relative_path: str) -> str:
        parts = path_parts(relative_path)
        if _DESCRIPTOR_PATHS:
            with self._open_directory(parts[:-1]) as parent:
                name = parts[-1]
                metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
                _reject_links(metadata)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("Expected a regular file.")
                descriptor = os.open(name, READ_FLAGS | _NOFOLLOW, dir_fd=parent)
                return read_descriptor(descriptor, metadata, MAX_FILE_BYTES).decode(
                    "utf-8-sig"
                )

        path = self._checked_path(parts)
        metadata = path.lstat()
        _reject_links(metadata)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Expected a regular file.")
        descriptor = os.open(path, READ_FLAGS)
        try:
            if not os.path.samestat(
                self._checked_path(parts).lstat(), os.fstat(descriptor)
            ):
                raise ValueError("Path changed while opening.")
        except BaseException:
            os.close(descriptor)
            raise
        return read_descriptor(descriptor, metadata, MAX_FILE_BYTES).decode("utf-8-sig")

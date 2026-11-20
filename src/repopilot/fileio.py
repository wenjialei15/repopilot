import os
import stat
from pathlib import Path

READ_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)


def read_descriptor(descriptor: int, expected: os.stat_result, limit: int) -> bytes:
    """Read a bounded regular file and take ownership of its descriptor."""
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(expected, opened):
            raise ValueError("File changed while opening.")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("File exceeds the size limit.")
    return data


def read_regular_file(path: Path, limit: int) -> bytes:
    # Explicit CLI file inputs may be symlinks, provided they resolve to a regular file.
    expected = path.stat()
    if not stat.S_ISREG(expected.st_mode):
        raise ValueError("Expected a regular file.")
    return read_descriptor(os.open(path, READ_FLAGS), expected, limit)

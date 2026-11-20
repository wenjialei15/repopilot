from importlib.metadata import version
from pathlib import Path, PurePosixPath
from tarfile import open as open_tar
from zipfile import ZipFile

from repopilot import DISTRIBUTION_NAME

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".venv",
    ".coverage",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "dist",
}


def require_files(names: set[str], required: set[str]) -> None:
    if missing := required - names:
        raise ValueError(f"Distribution is missing: {', '.join(sorted(missing))}")
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or EXCLUDED.intersection(path.parts)
        ):
            raise ValueError(f"Unexpected distribution entry: {name}")
        if path.suffix == ".pyc":
            raise ValueError(f"Unexpected bytecode in distribution: {name}")


def verify() -> None:
    package = f"{DISTRIBUTION_NAME.replace('-', '_')}-{version(DISTRIBUTION_NAME)}"
    source = ROOT / "src"
    modules = {
        file.relative_to(source).as_posix()
        for file in (source / "repopilot").rglob("*.py")
    }
    with ZipFile(ROOT / "dist" / f"{package}-py3-none-any.whl") as wheel:
        if wheel.testzip() is not None:
            raise ValueError("Wheel contains a corrupt entry.")
        required = modules | {
            f"{package}.dist-info/METADATA",
            f"{package}.dist-info/entry_points.txt",
            f"{package}.dist-info/licenses/LICENSE",
        }
        require_files(set(wheel.namelist()), required)
    with open_tar(ROOT / "dist" / f"{package}.tar.gz", "r:gz") as sdist:
        archive_members = set(sdist.getnames())
        required = {f"src/{module}" for module in modules} | {
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "tests/test_scan.py",
        }
        require_files(archive_members, {f"{package}/{name}" for name in required})
    print("Verified wheel and source distribution contents.")


if __name__ == "__main__":
    verify()

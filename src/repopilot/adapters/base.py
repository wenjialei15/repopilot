from typing import Protocol, runtime_checkable


class RepositoryAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_git_repository(self) -> bool: ...

    def read_text(self, relative_path: str) -> str: ...


@runtime_checkable
class FileListing(Protocol):
    def list_files(self, relative_directory: str) -> list[str]: ...


@runtime_checkable
class ExecutionEvidence(Protocol):
    def workflow_runs(self) -> list[str | None]: ...

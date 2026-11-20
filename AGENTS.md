# RepoPilot development instructions

Build a read-only, offline-first repository health auditor. Prefer deterministic, evidence-based rules. Keep CLI orchestration, repository adapters, rules, data models, scoring, planning, and rendering separate. Use stable rule IDs and versioned schemas. Preserve public interfaces, and distinguish pass, fail, unknown, and skip.

Use Python 3.11+, Typer, Rich, Pydantic v2, uv, hatchling, pytest, pytest-cov, Ruff, and mypy. Use httpx, respx, and PyYAML SafeLoader when the features that require them land. Keep support for Linux, macOS, and Windows.

Treat repository files as untrusted. Never execute target code. Use bounded reads and requests, reject path escapes, respect GitHub API limits, and avoid logging secrets or sensitive file contents.

Inspect existing changes before editing. Keep changes scoped, update tests and documentation, and report checks actually run and any remaining limitations. Obtain explicit user authorization before publishing or mutating GitHub resources.

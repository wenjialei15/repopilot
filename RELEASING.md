# Releasing RepoPilot

The source repository and CLI use the name RepoPilot. The Python distribution is `repopilot-health`.

## Prepare one commit

1. Confirm that the working tree is clean and that `pyproject.toml`, `uv.lock`, `repopilot --version`, and the changelog agree on the release version.
2. Confirm that every Windows, macOS, and Linux CI job succeeded for the exact commit to be tagged.
3. Confirm that the tag and GitHub Release do not exist and that the release account has access to the intended destinations.
4. Build from a clean checkout. Check the wheel and source distribution and run the installed wheel in an isolated environment.

```sh
uv sync --locked --group dev --no-editable
uv run --no-sync ruff check .
uv run --no-sync mypy src scripts
uv run --no-sync pytest --cov=repopilot --cov-fail-under=90
uv build
uv run --no-sync python scripts/verify_distribution.py
uv run --no-project --isolated --with ./dist/repopilot_health-0.1.0-py3-none-any.whl repopilot --version
uv run --no-project --isolated --with ./dist/repopilot_health-0.1.0-py3-none-any.whl repopilot scan .
```

## Publish an approved release

1. Create an annotated `v0.1.0` tag on the verified commit and push that tag.
2. Create a GitHub Release for the tag. Use the [v0.1.0 release notes](docs/release-notes-0.1.0.md) and attach the wheel, source distribution, and SHA-256 checksums.
3. If package-index publication is approved, verify control of the separate TestPyPI and PyPI projects. Configure a Trusted Publisher or use a project-scoped credential kept outside the repository. Upload the exact verified artifacts to TestPyPI and test installation. Resolve runtime dependencies from PyPI when checking a TestPyPI distribution.
4. Publish the same artifacts to PyPI after the TestPyPI check passes. Verify that a fresh environment installs `repopilot-health==0.1.0` and that `repopilot --version` returns `RepoPilot 0.1.0`.

Establishing package-index ownership and publishing the first distribution are separate from publishing the GitHub Release. See [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/).

## Recover from a release issue

Correct metadata or missing assets on an unpublished GitHub draft. If users can already install a faulty artifact, document the affected version, yank it on PyPI when appropriate, and publish corrected artifacts under a new version. Keep the tag and release history consistent with what users received.

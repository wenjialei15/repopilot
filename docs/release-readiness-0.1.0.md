# RepoPilot v0.1.0 release readiness

This report records the initial preparation checks for `release/0.1.0`. See [GitHub Releases](https://github.com/wenjialei15/repopilot/releases) for publication status.

| Check | Result |
| --- | --- |
| Phase 4 CI | All six Windows, macOS, and Ubuntu jobs passed for Python 3.11 and 3.13 at `6589009`. [CI run](https://github.com/wenjialei15/repopilot/actions/runs/44776898235) |
| Candidate CI | The versioning and distribution-name changes still need their own remote CI run. |
| Candidate local checks | Ruff and mypy passed. On Windows, 83 tests passed, 2 skipped, and statement coverage was 90.45%. |
| Build and installation | The wheel and source archive passed content checks and were each installed in an isolated Python 3.11 environment. Both returned `RepoPilot 0.1.0` and a 15-finding scan report. |
| Local release check | Six release checks passed. GitHub workflow execution is unknown in the local scan. |
| Runtime dependency advisories | PyPI's release metadata returned no active advisories for the 20 locked runtime dependency versions at the time of the check. [PyPI JSON API](https://docs.pypi.org/api/json/) |
| Tag and GitHub Release | GitHub returned 404 for both `v0.1.0` lookups. |
| Package index name | `repopilot` and `repopilot-cli` already exist on PyPI. `repopilot-health` returned 404 on PyPI and TestPyPI. Registration remains pending. [Existing repopilot package](https://pypi.org/project/repopilot/) · [Existing repopilot-cli package](https://pypi.org/project/repopilot-cli/) |
| Package index publication | TestPyPI installation from the index and PyPI publishing access remain unverified. No artifacts have been uploaded. |

The repository and executable use `repopilot`. The distribution metadata and artifact names use `repopilot-health`.

## Approval and release order

1. Push the release candidate branch and verify all six CI jobs on the candidate commit.
2. After approval, publish the tag and GitHub Release from that verified commit using the [release procedure](../RELEASING.md) and [release notes](release-notes-0.1.0.md).
3. For an approved package-index release, confirm ownership and publication access, verify a TestPyPI install, then publish the same verified artifacts to PyPI.

## v0.1.1 maintenance

Track installation, cross-platform scanning, and report compatibility defects from the first release. Reproduce reported defects with fixtures, keep report schema `1.0` compatible, and rerun the full CI matrix and isolated installation before publishing a patch.

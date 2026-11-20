# Phase 4 verification

## Review findings

| Severity | Finding | Change |
| --- | --- | --- |
| High | A path could change between the local repository check and directory enumeration. | Anchor reads and listings to directory descriptors where supported. On Windows, check directory identity and reject links or reparse points before using the result. |
| High | A successful run of an unrelated workflow could satisfy the CI release check. | Match runs on the scanned commit to workflows with recognizable test commands. Treat missing or unmatched runs as unknown. |
| Medium | GitHub failures could consume multiple retry sequences for the same tree and extend the scan. | Apply a scan-wide request and time budget. Remember unavailable trees for the life of the scan and reject redirects. |
| Medium | YAML structure and malformed JSON could exhaust parser work or produce ambiguous reports. | Limit YAML depth and event count, keep file-size caps, and reject duplicate keys and non-finite JSON values. |
| Medium | Explicit report and configuration inputs were checked before opening. | Check the identity and type of the open file before reading it. |
| Medium | CI used mutable GitHub Action tags. | Pin both actions to full commit SHAs and disable credential persistence in checkout. |

Windows uses path and identity checks because Python's descriptor-relative APIs used by the POSIX implementation are unavailable there. Concurrent renames remain a platform-specific limitation. The CI check verifies workflow outcomes at the selected commit. It cannot establish that every test step ran in a conditional workflow.

## Checks

- Windows Python 3.11.18 and 3.13.18 each passed 83 tests with 2 skips and 90.43% statement coverage. The Windows runner could not create a symbolic link and does not provide POSIX FIFOs.
- A separate Windows junction check confirmed the scanner marks a linked workflow directory as unknown.
- A public GitHub scan matched the successful `.github/workflows/ci.yml` run for the then-current default branch commit. See the [GitHub workflow runs API](https://docs.github.com/en/rest/actions/workflow-runs).
- CI retains Windows, Linux, and macOS jobs for Python 3.11 and 3.13 and now checks the 90% coverage threshold and distribution contents.
- Ruff and mypy passed. The wheel and source archive passed the distribution check, and a clean environment ran the installed wheel against the healthy fixture.
- All six Phase 4 CI jobs passed on Windows, Ubuntu, and macOS for Python 3.11 and 3.13 at commit `6589009`. [Phase 4 CI run](https://github.com/wenjialei15/repopilot/actions/runs/44776898235)

## Performance baseline

Windows with Python 3.11.18. Each scenario uses five warm-up scans and 30 timed samples. Memory is peak Python allocation from a separate measured scan. The remote fixture uses an in-process HTTP transport and measures RepoPilot overhead without network latency.

| Fixture | Median | P95 | Peak Python allocation | Requests per scan |
| --- | ---: | ---: | ---: | ---: |
| Local healthy fixture | 5.353 ms | 5.854 ms | 276,351 B | 0 |
| Mocked public GitHub fixture | 0.700 ms | 0.804 ms | 35,565 B | 4 |

```sh
uv run --no-sync python scripts/benchmark_scan.py
```

# RepoPilot

RepoPilot runs 15 evidence-based repository health checks from the command line. It scans local directories and public GitHub repositories and reports both a health score and evidence coverage.

## Run from source

With uv and Python 3.11 or newer:

```sh
uv sync --locked --group dev --no-editable
uv run --no-sync repopilot --help
uv run --no-sync repopilot --version
uv run --no-sync repopilot scan .
uv run --no-sync repopilot scan . --format terminal
uv run --no-sync repopilot scan github:octocat/hello-world
```

The installed package works in Windows paths with non-ASCII characters,
including on Python 3.11 with a legacy system code page. After editing the
source, rerun the sync command with `--reinstall-package repopilot-health` to refresh
the installed package.

The distribution name is `repopilot-health` and the command is `repopilot`.
To try a local v0.1.0 build in an isolated environment:

```sh
uv build
uv run --no-project --isolated --with ./dist/repopilot_health-0.1.0-py3-none-any.whl repopilot --version
```

A plain directory is scanned normally. For a local target, `is_git_repository` indicates whether the target root contains a regular `.git` file or directory. The scanner limits each file to 256 KiB and collects evidence without executing target code. Linked, oversized, and unreadable candidates yield `unknown` when they prevent a decision.

Remote scans read the head commit of the public repository's default branch. Set `GITHUB_TOKEN` for authenticated requests. Repository contents come from Git trees and blobs. CI run evidence uses the latest observed runs for workflows with recognizable test commands. RepoPilot budgets 45 seconds and 120 requests for a remote scan and waits at most ten seconds per retry. When GitHub requires a longer wait, affected evidence is unavailable. See [GitHub REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

A successful scan exits with code 0 even when a finding fails. Output goes to stdout unless you pass `--output`. Errors go to stderr.

## Rules and scoring

| Rule | Evidence evaluated | Weight |
| --- | --- | ---: |
| DOC001 | Nonempty README | 1 |
| DOC002 | Nonempty license file | 2 |
| DOC003 | Nonempty contribution guide | 1 |
| DOC004 | Nonempty security policy | 1 |
| SEC001 | Explicit `write-all` at workflow or job level | 2 |
| SEC002 | Remote actions and reusable workflows pinned to full commit SHAs | 2 |
| SEC003 | `pull_request_target` trigger that requires permission review | 2 |
| CI001 | GitHub Actions workflow files present | 2 |
| CI002 | Recognizable test command in a workflow step | 2 |
| CI003 | Latest observed GitHub Actions run results for the scanned commit | 2 |
| MAINT001 | Nonempty Dependabot or Renovate configuration | 1 |
| MAINT002 | Nonempty CODEOWNERS file | 1 |
| MAINT003 | Nonempty pull request template | 1 |
| REL001 | Nonempty changelog | 1 |
| REL002 | Nonempty release procedure | 1 |

File rules look for a readable, nonempty candidate at conventional paths. Workflow rules use static YAML evidence. The test command check recognizes common commands in direct `run` steps. Local scans report workflow run status as `unknown` when workflows exist.

The default JSON report retains the Phase 1 fields and adds `summary`. Score is the percentage of evaluated weight that passed. Evidence coverage is the percentage of applicable weight evaluated as `pass` or `fail`. The score is `null` when no rules can be evaluated. Rules marked `skip` and disabled rules are excluded from both calculations.

## Configuration

Pass an explicit YAML configuration with `--config`:

```sh
uv run --no-sync repopilot scan . --config repopilot.yml
```

```yaml
rules:
  SEC003: disabled
  CI002: enabled
```

All rules are enabled by default. Unknown rule IDs and invalid configuration values produce an error.

## Plan, compare, and check a release

```sh
uv run --no-sync repopilot scan . --output baseline.json
uv run --no-sync repopilot plan baseline.json --output PLAN.md
# Apply the chosen fixes, then scan the same target with the same rule settings.
uv run --no-sync repopilot scan . --output current.json
uv run --no-sync repopilot diff baseline.json current.json --output DIFF.md
uv run --no-sync repopilot release-check .
```

- `plan` turns failed checks into ordered tasks with supporting evidence, rough effort estimates, prerequisites where applicable, and acceptance criteria.
- `diff` matches findings by rule ID and resource. Reports from earlier versions default to a repository-wide resource. A failure is resolved when its current status is `pass`. A skipped, unknown, or absent check leaves the earlier failure unverified.
- `release-check` checks README, license, workflow and test configuration, observed CI results, changelog, and release procedure. A failure blocks readiness. Missing evidence leaves readiness incomplete when the other checks pass. A local scan leaves CI run evidence unknown when workflows are present. Run `release-check github:owner/repo` to evaluate observed GitHub Actions runs on the public default branch.

These three commands default to Markdown and accept `--format json` for automation. Use `scan --format markdown` for a Markdown scan report. `plan` and `diff` accept scan schema `1.0`.

| Exit code | Meaning |
| --- | --- |
| `0` | Command completed successfully, or all release checks passed |
| `1` | Release readiness is blocked or incomplete |
| `2` | Invalid arguments, target, configuration, or report input or output error |

## Development

```sh
uv run --no-sync pytest --cov=repopilot --cov-fail-under=90
uv run --no-sync ruff check .
uv run --no-sync mypy src scripts
uv build
uv run --no-sync python scripts/verify_distribution.py
uv run --no-sync python scripts/benchmark_scan.py
```

See the [release procedure](RELEASING.md), [Phase 4 verification report](docs/phase-4-verification.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the [Apache 2.0 license](LICENSE).

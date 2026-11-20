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
source, rerun the sync command with `--reinstall-package repopilot` to refresh
the installed package.

A plain directory is scanned normally. For a local target, `is_git_repository` indicates whether the target root contains a regular `.git` file or directory. The scanner limits each file to 256 KiB and collects evidence without executing target code. Linked, oversized, and unreadable candidates yield `unknown` when they prevent a decision.

Remote scans read the head commit of the public repository's default branch. Set `GITHUB_TOKEN` for authenticated requests. Repository contents come from Git trees and blobs. Workflow run results apply to the scanned commit and are limited to the latest observed run per workflow. If GitHub's retry delay exceeds ten seconds or the API advises a longer wait, RepoPilot leaves affected evidence unavailable. See [GitHub REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

A successful scan exits with code 0 even when a finding fails. An invalid scan target exits with code 2. JSON goes to stdout and errors go to stderr.

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

## Development

```sh
uv run --no-sync pytest --cov=repopilot
uv run --no-sync ruff check .
uv run --no-sync mypy src
uv build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Apache 2.0 license](LICENSE).

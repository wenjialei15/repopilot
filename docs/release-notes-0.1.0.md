# RepoPilot v0.1.0

RepoPilot scans a local directory or a public GitHub repository and turns its findings into an actionable maintenance plan.

- Run 15 configurable checks for project documentation, GitHub Actions, maintenance automation, and release preparation.
- Read a weighted health score alongside evidence coverage. Use JSON, Markdown, or a terminal scan report.
- Generate a prioritized plan with `plan`, compare two scans with `diff`, and evaluate release evidence with `release-check`.
- Scan GitHub repositories read-only. CI evidence applies to observed runs of recognized test workflows at the scanned commit.

RepoPilot requires Python 3.11 or newer. The distribution is `repopilot-health` and the command is `repopilot`. Install the wheel attached to the GitHub Release or build from source.

```sh
repopilot --version
repopilot scan .
repopilot scan github:octocat/hello-world --format terminal
```

Local scans cannot verify GitHub workflow run outcomes. Findings describe the evidence RepoPilot could collect, and release checks can report incomplete evidence.

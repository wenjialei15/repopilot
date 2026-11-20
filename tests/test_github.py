import base64

import httpx
import pytest
import respx
from typer.testing import CliRunner

from repopilot.adapters import github
from repopilot.adapters.github import (
    API_URL,
    MAX_RESPONSE_BYTES,
    GitHubError,
    GitHubRepository,
    github_client,
)
from repopilot.cli import app
from repopilot.models import ScanReport

BASE = f"{API_URL}/repos/acme/example"
HEAD, ROOT, DOT, WF, DOC, CI = (value * 40 for value in "abcdef")
WORKFLOW = b"on: push\njobs: {test: {steps: [{run: pytest}]}}\n"


def blob(name: str, sha: str, data: bytes) -> dict[str, object]:
    return {"path": name, "sha": sha, "mode": "100644", "size": len(data)}


def tree(name: str, sha: str) -> dict[str, str]:
    return {"path": name, "sha": sha, "mode": "040000"}


def trees(mock: respx.MockRouter) -> None:
    mock.get(BASE).respond(json={"private": False, "default_branch": "stable/v1"})
    mock.get(f"{BASE}/commits", params={"sha": "stable/v1", "per_page": "1"}).respond(
        json=[{"sha": HEAD, "commit": {"tree": {"sha": ROOT}}}]
    )
    for sha, items in (
        (ROOT, [blob("README.md", DOC, b"README"), tree(".github", DOT)]),
        (DOT, [tree("workflows", WF)]),
        (WF, [blob("ci.yml", CI, WORKFLOW)]),
    ):
        mock.get(f"{BASE}/git/trees/{sha}").respond(
            json={"truncated": False, "tree": items}
        )
    for sha, data in ((DOC, b"README"), (CI, WORKFLOW)):
        mock.get(f"{BASE}/git/blobs/{sha}").respond(
            json={
                "encoding": "base64",
                "content": base64.b64encode(data).decode("ascii"),
            }
        )


def run(conclusion: str | None, run_number: int) -> dict[str, object]:
    return {
        "workflow_id": 12,
        "path": ".github/workflows/ci.yml@refs/heads/stable/v1",
        "run_number": run_number,
        "run_attempt": 1,
        "head_sha": HEAD,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
    }


@pytest.mark.parametrize(
    ("latest", "status"),
    [("success", "pass"), ("failure", "fail"), (None, "unknown")],
)
def test_github_cli(latest: str | None, status: str) -> None:
    with respx.mock as mock:
        trees(mock)
        runs = mock.get(
            f"{BASE}/actions/runs", params={"head_sha": HEAD, "per_page": "100"}
        ).respond(
            json={
                "total_count": 2,
                "workflow_runs": [run("failure", 1), run(latest, 2)],
            }
        )
        result = CliRunner().invoke(
            app,
            ["scan", "github:acme/example"],
            env={"GITHUB_TOKEN": "private-test-token"},
        )
    assert result.exit_code == 0, result.output
    assert "private-test-token" not in result.output
    report = ScanReport.model_validate_json(result.stdout)
    findings = {finding.rule_id: finding.status for finding in report.findings}
    assert findings["DOC001"] == "pass"
    assert findings["CI002"] == "pass"
    assert findings["CI003"] == status
    assert len(report.findings) == 15
    assert (
        runs.calls.last.request.headers["Authorization"] == "Bearer private-test-token"
    )


@pytest.mark.parametrize(
    ("status", "headers", "waits"),
    [
        (401, {}, []),
        (403, {}, []),
        (404, {}, []),
        (429, {}, []),
        (429, {"Retry-After": "120"}, []),
        (429, {"Retry-After": "3"}, [3, 3]),
        (403, {"Retry-After": "1"}, [1, 1]),
        (503, {}, [1, 2]),
    ],
)
def test_request_retries(
    status: int, headers: dict[str, str], waits: list[float]
) -> None:
    actual_waits: list[float] = []
    with respx.mock as mock, github_client("example-token") as client:
        route = mock.get(BASE).respond(
            status, headers=headers, text="untrusted content"
        )
        with pytest.raises(GitHubError) as exc:
            GitHubRepository(client, "acme/example", sleep=actual_waits.append)
    assert route.call_count == len(waits) + 1
    assert waits == actual_waits
    assert "untrusted content" not in str(exc.value)


def test_timeout_retry_then_authentication_error() -> None:
    with respx.mock as mock, github_client(None) as client:
        route = mock.get(BASE)
        route.side_effect = [httpx.ReadTimeout("ignored"), httpx.Response(401)]
        waits: list[float] = []
        with pytest.raises(GitHubError, match="authentication"):
            GitHubRepository(client, "acme/example", sleep=waits.append)
    assert waits == [1]


@pytest.mark.parametrize(
    ("body", "message"),
    [(b" " * (MAX_RESPONSE_BYTES + 1), "limit"), (b"invalid", "invalid JSON")],
)
def test_invalid_response(body: bytes, message: str) -> None:
    with respx.mock as mock, github_client(None) as client:
        mock.get(BASE).respond(content=body)
        with pytest.raises(GitHubError, match=message):
            GitHubRepository(client, "acme/example")


def test_private_repo_stops_before_reading_content() -> None:
    with respx.mock as mock, github_client(None) as client:
        mock.get(BASE).respond(json={"private": True, "default_branch": "main"})
        with pytest.raises(GitHubError, match="Only public"):
            GitHubRepository(client, "acme/example")


def test_unrelated_workflow_cannot_satisfy_ci() -> None:
    with respx.mock as mock:
        trees(mock)
        unrelated = {**run("success", 1), "path": ".github/workflows/docs.yml"}
        mock.get(f"{BASE}/actions/runs").respond(
            json={"total_count": 1, "workflow_runs": [unrelated]}
        )
        result = CliRunner().invoke(app, ["scan", "github:acme/example"])
    assert result.exit_code == 0, result.output
    report = ScanReport.model_validate_json(result.stdout)
    assert next(item for item in report.findings if item.rule_id == "CI003").status == (
        "unknown"
    )


def test_retry_respects_the_scan_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "SCAN_TIMEOUT", 1)
    waits: list[float] = []
    with respx.mock as mock, github_client(None) as client:
        route = mock.get(BASE).respond(429, headers={"Retry-After": "3"})
        with pytest.raises(GitHubError, match="rate limit"):
            GitHubRepository(client, "acme/example", sleep=waits.append)
    assert route.call_count == 1
    assert not waits


def test_failed_tree_is_not_retried_by_each_rule() -> None:
    with respx.mock(assert_all_called=False) as mock, github_client(None) as client:
        trees(mock)
        route = mock.get(f"{BASE}/git/trees/{ROOT}").respond(503)
        repo = GitHubRepository(client, "acme/example", sleep=lambda _: None)
        for filename in ("README.md", "LICENSE"):
            with pytest.raises(GitHubError):
                repo.read_text(filename)
    assert route.call_count == 3


def test_adapter_refuses_redirect_with_caller_supplied_client() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(302, headers={"Location": "https://example.invalid/"})

    with (
        httpx.Client(
            transport=httpx.MockTransport(redirect), follow_redirects=True
        ) as client,
        pytest.raises(GitHubError, match="HTTP 302"),
    ):
        GitHubRepository(client, "acme/example")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"truncated": True, "tree": []}, "incomplete"),
        ({"truncated": False, "tree": [tree("same", WF)] * 2}, "invalid tree entry"),
        ({"truncated": False, "tree": [{"path": "README.md"}]}, "invalid tree entry"),
    ],
)
def test_invalid_tree_is_unavailable(payload: object, message: str) -> None:
    with respx.mock(assert_all_called=False) as mock, github_client(None) as client:
        trees(mock)
        mock.get(f"{BASE}/git/trees/{ROOT}").respond(json=payload)
        repo = GitHubRepository(client, "acme/example")
        with pytest.raises(GitHubError, match=message):
            repo.read_text("README.md")


@pytest.mark.parametrize(
    ("content", "encoding", "message"),
    [
        ("!", "base64", "encoding was invalid"),
        ("YQ==", "base64", "size did not match"),
        ("README", "raw", "Expected a base64"),
    ],
)
def test_invalid_blob_is_rejected(content: str, encoding: str, message: str) -> None:
    with respx.mock(assert_all_called=False) as mock, github_client(None) as client:
        trees(mock)
        mock.get(f"{BASE}/git/blobs/{DOC}").respond(
            json={"encoding": encoding, "content": content}
        )
        repo = GitHubRepository(client, "acme/example")
        with pytest.raises(ValueError, match=message):
            repo.read_text("README.md")


def test_invalid_token_and_target_return_cli_errors() -> None:
    runner = CliRunner()
    for target, token, expected in (
        ("github:acme/..", "example-token", "owner/repo"),
        ("github:acme/example", "invalid token", "invalid characters"),
    ):
        result = runner.invoke(app, ["scan", target], env={"GITHUB_TOKEN": token})
        assert result.exit_code == 2
        assert expected in result.stderr
        assert token not in result.output

import base64
import binascii
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import httpx

from repopilot.adapters.paths import MAX_FILE_BYTES, path_parts

API_URL = "https://api.github.com"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ATTEMPTS = 3
MAX_WAIT_SECONDS = 10
MAX_REQUESTS = 120
OWNER = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?")
REPOSITORY = re.compile(r"[a-zA-Z0-9_.-]{1,100}")
SHA = re.compile(r"[0-9a-f]{40}")


class GitHubError(OSError):
    """GitHub evidence could not be retrieved."""


def parse_target(target: str) -> tuple[str, str]:
    parts = target.removeprefix("github:").split("/")
    if (
        len(parts) != 2
        or not OWNER.fullmatch(parts[0])
        or not REPOSITORY.fullmatch(parts[1])
        or parts[1] in {".", ".."}
    ):
        raise ValueError("Expected a GitHub repository in github:owner/repo form.")
    return parts[0], parts[1]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GitHubError("GitHub returned an unexpected response.")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise GitHubError("GitHub returned an unexpected response.")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise GitHubError("GitHub returned an invalid object identifier.")
    return value


def _read_json(response: httpx.Response) -> object:
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise GitHubError("GitHub returned an unsupported response encoding.")
    data = bytearray()
    deadline = time.monotonic() + 15
    for chunk in response.iter_bytes(chunk_size=16 * 1024):
        if len(data) + len(chunk) > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
            raise GitHubError("GitHub response exceeded the download limit.")
        data.extend(chunk)
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        raise GitHubError("GitHub returned an invalid JSON response.") from None


def _retry_delay(response: httpx.Response, attempt: int) -> float | None:
    retry_after = response.headers.get("retry-after", "")
    remaining = response.headers.get("x-ratelimit-remaining")
    if retry_after.isascii() and retry_after.isdigit() and len(retry_after) <= 10:
        return float(retry_after)
    if remaining == "0":
        reset = response.headers.get("x-ratelimit-reset", "")
        if reset.isascii() and reset.isdigit() and len(reset) <= 12:
            return max(0.0, float(reset) - time.time()) + 1
        return None
    if response.status_code == 429 or response.status_code == 403:
        # GitHub recommends at least one minute for unqualified secondary limits.
        return None
    return float(2**attempt)


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    sha: str
    size: int | None


class GitHubRepository:
    def __init__(
        self,
        client: httpx.Client,
        target: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        owner, repo = parse_target(target)
        self.name = f"github:{owner.lower()}/{repo.lower()}"
        self.is_git_repository = True
        self._endpoint = f"/repos/{owner}/{repo}"
        self._client = client
        self._sleep = sleep
        self._requests = 0
        self._limit_reached = False
        self._trees: dict[str, dict[str, TreeEntry]] = {}

        metadata = _object(self._get(""))
        if metadata.get("private") is not False or metadata.get("visibility") not in (
            None,
            "public",
        ):
            raise GitHubError("Only public GitHub repositories can be scanned.")
        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise GitHubError("GitHub repository has no readable default branch.")
        commits = _array(self._get("/commits", {"sha": branch, "per_page": "1"}))
        if not commits:
            raise GitHubError("GitHub repository has no commits to scan.")
        commit = _object(commits[0])
        self._commit_sha = _sha(commit.get("sha"))
        self._tree_sha = _sha(
            _object(_object(commit.get("commit")).get("tree")).get("sha")
        )

    def _get(self, suffix: str, params: dict[str, str] | None = None) -> object:
        for attempt in range(MAX_ATTEMPTS):
            if self._limit_reached or self._requests >= MAX_REQUESTS:
                raise GitHubError("GitHub request budget was exhausted.")
            self._requests += 1
            try:
                with self._client.stream(
                    "GET", f"{API_URL}{self._endpoint}{suffix}", params=params
                ) as response:
                    status = response.status_code
                    if status == 200:
                        return _read_json(response)
                    if status == 404:
                        raise GitHubError(
                            "GitHub resource was not found or is inaccessible."
                        )
                    if status == 409:
                        raise GitHubError(
                            "GitHub repository data is empty or unavailable."
                        )
                    if status == 401:
                        raise GitHubError("GitHub authentication failed.")
                    limited = status == 429 or (
                        status == 403
                        and (
                            response.headers.get("x-ratelimit-remaining") == "0"
                            or "retry-after" in response.headers
                        )
                    )
                    if limited or 500 <= status <= 599:
                        delay = _retry_delay(response, attempt)
                    elif status == 403:
                        self._limit_reached = True
                        raise GitHubError(
                            "GitHub denied the request or applied a rate limit."
                        )
                    else:
                        raise GitHubError(f"GitHub request failed (HTTP {status}).")
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ):
                limited = False
                delay = float(2**attempt)
            except (httpx.HTTPError, UnicodeError):
                raise GitHubError("GitHub response could not be read.") from None

            if attempt == MAX_ATTEMPTS - 1 or delay is None or delay > MAX_WAIT_SECONDS:
                if limited:
                    self._limit_reached = True
                    raise GitHubError(
                        "GitHub rate limit reached. Try again later."
                    ) from None
                raise GitHubError(
                    "GitHub did not respond successfully after retries."
                ) from None
            self._sleep(delay)
        raise AssertionError("Retry limit must be positive.")

    def _tree(self, sha: str) -> dict[str, TreeEntry]:
        if sha not in self._trees:
            tree = _object(self._get(f"/git/trees/{sha}"))
            if tree.get("truncated") is not False:
                raise GitHubError("GitHub tree listing was incomplete.")
            entries = {}
            for value in _array(tree.get("tree")):
                item = _object(value)
                name, mode, size = item.get("path"), item.get("mode"), item.get("size")
                if (
                    not isinstance(name, str)
                    or "/" in name
                    or not isinstance(mode, str)
                ):
                    raise GitHubError("GitHub returned an invalid tree entry.")
                entries[name] = TreeEntry(
                    mode, _sha(item.get("sha")), size if type(size) is int else None
                )
            self._trees[sha] = entries
        return self._trees[sha]

    def _entry(self, path: str) -> TreeEntry:
        parts = path_parts(path)
        tree_sha = self._tree_sha
        for part in parts[:-1]:
            directory = self._tree(tree_sha).get(part)
            if directory is None:
                raise FileNotFoundError(path)
            if directory.mode != "040000":
                raise ValueError("Expected a Git tree directory.")
            tree_sha = directory.sha
        entry = self._tree(tree_sha).get(parts[-1])
        if entry is None:
            raise FileNotFoundError(path)
        return entry

    def list_files(self, relative_directory: str) -> list[str]:
        try:
            directory = self._entry(relative_directory)
        except FileNotFoundError:
            return []
        if directory.mode != "040000":
            raise ValueError("Expected a Git tree directory.")
        return [
            f"{relative_directory}/{name}"
            for name, entry in sorted(self._tree(directory.sha).items())
            if entry.mode != "040000"
        ]

    def read_text(self, relative_path: str) -> str:
        entry = self._entry(relative_path)
        if entry.mode not in {"100644", "100755"} or entry.size is None:
            raise ValueError("Expected a regular Git blob with a known size.")
        if not 0 <= entry.size <= MAX_FILE_BYTES:
            raise ValueError("File exceeds the scan size limit.")
        blob = _object(self._get(f"/git/blobs/{entry.sha}"))
        content = blob.get("content")
        if blob.get("encoding") != "base64" or not isinstance(content, str):
            raise ValueError("Expected a base64 Git blob.")
        try:
            data = base64.b64decode("".join(content.splitlines()), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Git blob encoding was invalid.") from None
        if len(data) != entry.size:
            raise ValueError("Git blob size did not match its tree entry.")
        return data.decode("utf-8-sig")

    def workflow_runs(self) -> list[str | None]:
        payload = _object(
            self._get(
                "/actions/runs", {"head_sha": self._commit_sha, "per_page": "100"}
            )
        )
        runs = _array(payload.get("workflow_runs"))
        count = payload.get("total_count")
        if not isinstance(count, int) or count != len(runs):
            raise GitHubError("Workflow run listing was incomplete.")
        latest: dict[int, tuple[int, int, str | None]] = {}
        for value in runs:
            run = _object(value)
            workflow_id, run_number, run_attempt = (
                run.get("workflow_id"),
                run.get("run_number"),
                run.get("run_attempt"),
            )
            if (
                not isinstance(workflow_id, int)
                or not isinstance(run_number, int)
                or not isinstance(run_attempt, int)
                or run.get("head_sha") != self._commit_sha
            ):
                raise GitHubError("GitHub returned unexpected workflow run metadata.")
            conclusion = run.get("conclusion")
            result = (
                conclusion
                if (run.get("status") == "completed" and isinstance(conclusion, str))
                else None
            )
            previous = latest.get(workflow_id)
            if previous is None or (run_number, run_attempt) > previous[:2]:
                latest[workflow_id] = (run_number, run_attempt, result)
        return [item[2] for item in latest.values()]


def github_client(token: str | None) -> httpx.Client:
    headers = {
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "identity",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "RepoPilot",
    }
    if token:
        if not token.isascii() or any(not 33 <= ord(char) <= 126 for char in token):
            raise GitHubError("GitHub token contains invalid characters.")
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(
        headers=headers,
        timeout=httpx.Timeout(8, connect=5),
        follow_redirects=False,
        trust_env=False,
    )

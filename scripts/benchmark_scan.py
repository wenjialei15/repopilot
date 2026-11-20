import base64
import json
from collections.abc import Callable
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter
from tracemalloc import get_traced_memory, start, stop

import httpx

from repopilot.adapters.github import GitHubRepository
from repopilot.adapters.local import LocalRepository
from repopilot.scan import scan_repository

ROOT = Path(__file__).resolve().parents[1]
BASE = "/repos/benchmark/fixture"
HEAD, TREE, BLOB = (character * 40 for character in "abc")
README = (ROOT / "tests/fixtures/healthy/README.md").read_bytes()


def benchmark(scan: Callable[[], int]) -> dict[str, float | int]:
    for _ in range(5):
        scan()
    timings = []
    counts = set()
    for _ in range(30):
        before = perf_counter()
        counts.add(scan())
        timings.append((perf_counter() - before) * 1000)
    start()
    try:
        scan()
        _, peak = get_traced_memory()
    finally:
        stop()
    if len(counts) != 1:
        raise RuntimeError("Request count changed across the fixed fixture.")
    return {
        "samples": len(timings),
        "median_ms": round(median(timings), 3),
        "p95_ms": round(quantiles(timings, n=20, method="inclusive")[-1], 3),
        "peak_python_allocations_bytes": peak,
        "requests_per_scan": counts.pop(),
    }


def local_scan() -> int:
    scan_repository(LocalRepository(ROOT / "tests/fixtures/healthy"))
    return 0


def remote_scan() -> int:
    responses = {
        BASE: {"private": False, "default_branch": "main"},
        f"{BASE}/commits": [{"sha": HEAD, "commit": {"tree": {"sha": TREE}}}],
        f"{BASE}/git/trees/{TREE}": {
            "truncated": False,
            "tree": [
                {
                    "path": "README.md",
                    "mode": "100644",
                    "sha": BLOB,
                    "size": len(README),
                }
            ],
        },
        f"{BASE}/git/blobs/{BLOB}": {
            "encoding": "base64",
            "content": base64.b64encode(README).decode("ascii"),
        },
    }
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=responses[request.url.path])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        scan_repository(GitHubRepository(client, "benchmark/fixture"))
    return requests


if __name__ == "__main__":
    print(
        json.dumps(
            {"local": benchmark(local_scan), "mocked_github": benchmark(remote_scan)},
            indent=2,
        )
    )

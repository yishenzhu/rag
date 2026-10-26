"""Concurrent load test for the memory API (create + search + list)."""

import argparse
import asyncio
import os
import time
from random import choice
from uuid import uuid4

from rag.sdk import RagClient

QUERIES = [
    "dark theme",
    "deploy checklist",
    "customer feedback",
    "release notes",
    "incident review",
]


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile in the same units as values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * pct / 100), len(ordered) - 1)
    return ordered[index]


async def run_phase(name: str, total: int, concurrency: int, call) -> int:
    latencies: list[float] = []
    failures = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def one(index: int) -> None:
        nonlocal failures
        async with semaphore:
            started = time.perf_counter()
            try:
                await call(index)
            except Exception:  # noqa: BLE001
                failures += 1
                return
            latencies.append(time.perf_counter() - started)

    started = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(total)))
    elapsed = time.perf_counter() - started
    print(
        f"{name}: {total} req in {elapsed:.1f}s, {total / elapsed:.1f} rps, "
        f"p50 {percentile(latencies, 50) * 1000:.0f}ms, "
        f"p95 {percentile(latencies, 95) * 1000:.0f}ms, "
        f"p99 {percentile(latencies, 99) * 1000:.0f}ms, "
        f"errors {failures}"
    )
    return failures


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load test the memory API")
    parser.add_argument("--url", default=os.getenv("API_URL", "http://localhost:8001"))
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--email", help="reuse an existing user instead of registering")
    parser.add_argument("--password", default="secret123")
    args = parser.parse_args()

    async with RagClient(args.url) as client:
        if args.email:
            await client.login(args.email, args.password)
            projects = await client.list_projects()
            if not projects:
                raise SystemExit("user has no projects")
            project_id = projects[0]["id"]
        else:
            email = f"load-{uuid4().hex[:8]}@example.com"
            registered = await client.register(email, args.password, "Load")
            project_id = registered["project_id"]
            print("registered", email)

        created_key = await client.create_api_key(
            project_id, "loadtest", ["memories:read", "memories:write"]
        )
        client.api_key = created_key["key"]
        client.token = None

        failures = 0
        failures += await run_phase(
            "create",
            args.requests,
            args.concurrency,
            lambda i: client.create_memory(
                f"load memory {uuid4().hex} about {choice(QUERIES)}",
                metadata={"run": "load"},
            ),
        )
        failures += await run_phase(
            "search",
            args.requests,
            args.concurrency,
            lambda i: client.search_memories(choice(QUERIES), top_k=5),
        )
        failures += await run_phase(
            "list",
            args.requests,
            args.concurrency,
            lambda i: client.list_memories(limit=20),
        )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

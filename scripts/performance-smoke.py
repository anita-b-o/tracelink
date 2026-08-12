#!/usr/bin/env python3
"""Small, non-destructive authenticated performance smoke for a local test stack."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from typing import Any

import httpx


BASE_URL = os.getenv("PERF_BASE_URL", "http://backend:8000")
ORIGIN = os.getenv("PERF_ORIGIN", "http://localhost:3100")
EMAIL = os.getenv("PERF_EMAIL", "e2e@example.com")
PASSWORD = os.getenv("PERF_PASSWORD", "e2e-password-secure")


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * value) - 1)]


async def main() -> None:
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        csrf_response = await client.get("/api/auth/csrf")
        csrf_response.raise_for_status()
        csrf = csrf_response.json()["csrf_token"]
        unsafe_headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        login = await client.post(
            "/api/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            headers=unsafe_headers,
        )
        login.raise_for_status()
        csrf = client.cookies["tracelink_csrf"]
        unsafe_headers["X-CSRF-Token"] = csrf

        create_ms: list[float] = []
        created_ids: list[str] = []
        for index in range(5):
            started = time.perf_counter()
            response = await client.post(
                "/api/investigations",
                json={
                    "title": f"Performance smoke {time.time_ns()}-{index}",
                    "original_query": "Local concurrency smoke; no external providers.",
                },
                headers=unsafe_headers,
            )
            response.raise_for_status()
            create_ms.append((time.perf_counter() - started) * 1000)
            created_ids.append(response.json()["id"])

        concurrency = asyncio.Semaphore(10)

        async def dashboard_request() -> float:
            async with concurrency:
                started = time.perf_counter()
                response = await client.get("/api/investigations?limit=100")
                response.raise_for_status()
                return (time.perf_counter() - started) * 1000

        dashboard_ms = await asyncio.gather(*(dashboard_request() for _ in range(50)))
        investigations = (await client.get("/api/investigations?limit=100")).json()
        subject = next(
            (
                item
                for item in investigations
                if item["status"] == "COMPLETED" and item["counts"]["documents"] > 0
            ),
            investigations[0],
        )
        investigation_id = subject["id"]

        async def measure(method: str, path: str, **kwargs: Any) -> tuple[float, int]:
            started = time.perf_counter()
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return (time.perf_counter() - started) * 1000, response.status_code

        detail_ms, _ = await measure("GET", f"/api/investigations/{investigation_id}")
        graph_ms, _ = await measure(
            "GET", f"/api/investigations/{investigation_id}/graph?max_nodes=250"
        )
        search_ms, _ = await measure(
            "POST",
            f"/api/investigations/{investigation_id}/search",
            json={"query": "director ownership", "top_k": 10},
            headers=unsafe_headers,
        )
        ask_ms, _ = await measure(
            "POST",
            f"/api/investigations/{investigation_id}/ask",
            json={"question": "Who is a director?"},
            headers=unsafe_headers,
        )
        report_ms, report_status = await measure(
            "POST",
            f"/api/investigations/{investigation_id}/reports",
            json={"type": "TIMELINE_SUMMARY"},
            headers=unsafe_headers,
        )

        print(
            json.dumps(
                {
                    "created_investigations": len(created_ids),
                    "dashboard_requests": 50,
                    "dashboard_concurrency": 10,
                    "dashboard_ms": {
                        "p50": round(percentile(dashboard_ms, 0.50), 3),
                        "p95": round(percentile(dashboard_ms, 0.95), 3),
                    },
                    "investigation_create_ms": {
                        "p50": round(percentile(create_ms, 0.50), 3),
                        "p95": round(percentile(create_ms, 0.95), 3),
                    },
                    "detail_ms": round(detail_ms, 3),
                    "graph_ms": round(graph_ms, 3),
                    "hybrid_search_ms": round(search_ms, 3),
                    "ask_fake_ms": round(ask_ms, 3),
                    "report_enqueue_ms": round(report_ms, 3),
                    "report_status": report_status,
                },
                separators=(",", ":"),
            )
        )


if __name__ == "__main__":
    asyncio.run(main())

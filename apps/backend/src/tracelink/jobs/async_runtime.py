import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from tracelink.infrastructure.database import close_database

ResultT = TypeVar("ResultT")


class AsyncWorkerRuntime:
    """Own one reusable asyncio loop inside each synchronous Celery worker process."""

    def __init__(self) -> None:
        self._runner: asyncio.Runner | None = None

    def run(self, coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(coroutine)

    def close(self) -> None:
        if self._runner is None:
            return
        self._runner.run(close_database())
        self._runner.close()
        self._runner = None


async_worker_runtime = AsyncWorkerRuntime()

"""Vercel FastAPI entrypoint; reuses the production application instance."""

from __future__ import annotations

import os

os.environ["TRACELINK_SERVERLESS"] = "true"

from tracelink.core.config import get_settings  # noqa: E402
from tracelink.main import app  # noqa: E402
from tracelink.vercel_demo import RequestTriggeredOutboxMiddleware  # noqa: E402

app.add_middleware(RequestTriggeredOutboxMiddleware, settings=get_settings())

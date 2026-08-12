from __future__ import annotations

import hmac
import re
import uuid

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tracelink.core.config import Settings
from tracelink.core.logging import request_id_context

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestSecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_context.set(request_id)

        async def response_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if self.settings.app_env in {"staging", "production"}:
                    headers["Content-Security-Policy"] = (
                        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
                        "form-action 'none'"
                    )
                if self.settings.app_env == "production":
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        try:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    too_large = int(content_length) > self.settings.max_request_body_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    await JSONResponse(
                        {"detail": "request body too large", "request_id": request_id},
                        status_code=413,
                    )(scope, receive, response_send)
                    return

            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(
                "/api/"
            ):
                if not self.settings.test_auth_bypass:
                    origin = request.headers.get("origin")
                    csrf_cookie = request.cookies.get("tracelink_csrf")
                    csrf_header = request.headers.get("x-csrf-token")
                    if (
                        origin not in self.settings.cors_origin_list
                        or not csrf_cookie
                        or not csrf_header
                        or not hmac.compare_digest(csrf_cookie, csrf_header)
                    ):
                        await JSONResponse(
                            {"detail": "CSRF validation failed", "request_id": request_id},
                            status_code=403,
                        )(scope, receive, response_send)
                        return

            buffered: list[Message] = []
            consumed = 0
            while True:
                message = await receive()
                buffered.append(message)
                if message["type"] != "http.request":
                    break
                consumed += len(message.get("body", b""))
                if consumed > self.settings.max_request_body_bytes:
                    await JSONResponse(
                        {"detail": "request body too large", "request_id": request_id},
                        status_code=413,
                    )(scope, receive, response_send)
                    return
                if not message.get("more_body", False):
                    break

            position = 0

            async def replay_receive() -> Message:
                nonlocal position
                if position < len(buffered):
                    message = buffered[position]
                    position += 1
                    return message
                return {"type": "http.disconnect"}

            await self.app(scope, replay_receive, response_send)
        finally:
            request_id_context.reset(token)

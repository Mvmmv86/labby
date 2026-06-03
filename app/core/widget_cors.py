from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

WIDGET_CORS_METHODS = "GET, POST, OPTIONS"
WIDGET_CORS_DEFAULT_HEADERS = "Content-Type"
WIDGET_CORS_MAX_AGE = "600"


class WidgetCORSMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/widget/"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if scope.get("method") == "OPTIONS":
            response = Response(status_code=204)
            self._apply_cors_headers(
                response.headers,
                origin=origin,
                requested_headers=headers.get("access-control-request-headers"),
            )
            await response(scope, receive, send)
            return

        async def send_with_widget_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                self._apply_cors_headers(
                    response_headers,
                    origin=origin,
                    requested_headers=headers.get("access-control-request-headers"),
                )
            await send(message)

        await self.app(scope, receive, send_with_widget_cors)

    @staticmethod
    def _apply_cors_headers(
        headers: MutableHeaders | dict[str, Any],
        *,
        origin: str | None,
        requested_headers: str | None,
    ) -> None:
        headers["Access-Control-Allow-Origin"] = origin or "*"
        headers["Access-Control-Allow-Methods"] = WIDGET_CORS_METHODS
        headers["Access-Control-Allow-Headers"] = (
            requested_headers or WIDGET_CORS_DEFAULT_HEADERS
        )
        headers["Access-Control-Max-Age"] = WIDGET_CORS_MAX_AGE
        if "Access-Control-Allow-Credentials" in headers:
            del headers["Access-Control-Allow-Credentials"]
        if origin:
            existing_vary = str(headers.get("Vary", ""))
            vary_values = {item.strip() for item in existing_vary.split(",") if item.strip()}
            vary_values.add("Origin")
            headers["Vary"] = ", ".join(sorted(vary_values))


WidgetCORSCallable = Callable[[Scope, Receive, Send], Awaitable[None]]

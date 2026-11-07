"""Authenticated, loopback-only MCP transport for local browser clients."""

import logging
import secrets
from pathlib import Path
from urllib.parse import urlparse

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

DEFAULT_ORIGINS = ("http://localhost:8080", "http://127.0.0.1:8080")


class BearerAuth:
    def __init__(self, app, token, origins):
        self.app, self.token, self.origins = app, token, set(origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            origin = headers.get(b"origin", b"").decode("latin1")
            authorization = headers.get(b"authorization", b"")
            if origin and origin not in self.origins:
                await JSONResponse({"error": "origin_not_allowed"}, status_code=403)(
                    scope, receive, send
                )
                return
            if not secrets.compare_digest(authorization, ("Bearer " + self.token).encode()):
                await JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


def make_http_app(mcp, token, origins=DEFAULT_ORIGINS):
    for origin in origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.path not in ("", "/")
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("MCP HTTP origins must be explicit local HTTP origins")
    mcp.settings.json_response = True
    mcp.settings.max_sessions = 16
    mcp.settings.session_idle_timeout = 300
    inner = mcp.streamable_http_app()
    return CORSMiddleware(
        BearerAuth(inner, token, origins),
        allow_origins=list(origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Mcp-Session-Id",
            "Mcp-Protocol-Version",
            "Last-Event-ID",
        ],
        expose_headers=["Mcp-Session-Id"],
    )


def load_http_token(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as stream:
            stream.write(secrets.token_hex(32))
        path.chmod(0o600)
    except FileExistsError:
        pass
    token = path.read_text().strip()
    if len(token) < 32 or not token.isascii():
        raise ValueError("MCP HTTP token must contain at least 32 ASCII characters")
    return token


def serve(mcp, port, token_file, origins):
    import uvicorn

    if not 1 <= port <= 65535:
        raise ValueError("Invalid MCP HTTP port")
    # SDK info messages include session identifiers; keep them out of logs.
    logging.getLogger("mcp").setLevel(logging.WARNING)
    app = make_http_app(mcp, load_http_token(token_file), origins or DEFAULT_ORIGINS)
    print(
        f"MCP URL: http://127.0.0.1:{port}/mcp\nBearer token file: {Path(token_file).resolve()}",
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")

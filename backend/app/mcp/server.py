"""MCP server transport layer for FitWar.

Provides two transports selectable at runtime:

1. **stdio** (default for local dev / Claude Desktop)
   Run ``python -m app.mcp.server`` and point your MCP client at the process.

2. **SSE** (for Render / production — mounted as a FastAPI sub-application)
   Call ``build_mcp_app()`` and ``app.mount("/mcp", build_mcp_app())``.

The transport layer is intentionally thin: it speaks the wire protocol and
delegates every tool call to ``app.mcp.tools.call_tool``.  No business logic
lives here.

Wire protocol (MCP 2024-11-05)
-------------------------------
Initialize  → ``initialize`` / ``initialized``
List tools  → ``tools/list``
Call a tool → ``tools/call``

Only the subset required for tool use is implemented here; prompts and
resources are left as stubs for a future phase.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from app.mcp.tools import call_tool, list_tools

# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "fitwar-mcp", "version": "0.1.0"}

_CAPABILITIES: dict[str, Any] = {
    "tools": {"listChanged": False},
    "prompts": {},      # stubs — not yet implemented
    "resources": {},    # stubs — not yet implemented
}


def _ok(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": payload}


# Standard JSON-RPC error codes
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Request handler (transport-agnostic)
# ---------------------------------------------------------------------------


def handle_request(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC request dict and return a response dict.

    Returns ``None`` for notifications (no ``id`` field) so callers know
    not to write a response back to the client.
    """
    id_ = raw.get("id")
    method = raw.get("method", "")
    params = raw.get("params") or {}

    # Notifications have no id; acknowledge silently.
    is_notification = "id" not in raw

    try:
        if method == "initialize":
            result = {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "capabilities": _CAPABILITIES,
            }
            return _ok(id_, result) if not is_notification else None

        if method == "initialized":
            return None  # always a notification — no response

        if method == "tools/list":
            tools = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    # Minimal inputSchema — a future phase can introspect
                    # the actual function signature and emit a real schema.
                    "inputSchema": {"type": "object"},
                }
                for t in list_tools()
            ]
            return _ok(id_, {"tools": tools})

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}
            try:
                output = call_tool(tool_name, arguments)
            except KeyError:
                return _err(id_, _INVALID_PARAMS, f"Unknown tool: {tool_name!r}")
            except TypeError as exc:
                return _err(id_, _INVALID_PARAMS, f"Bad arguments for {tool_name!r}: {exc}")
            return _ok(
                id_,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(output, default=str)}
                    ],
                    "isError": False,
                },
            )

        if method in ("prompts/list", "resources/list"):
            # Stubs: return empty lists rather than method-not-found so clients
            # that probe all three capability categories don't error out.
            key = "prompts" if "prompts" in method else "resources"
            return _ok(id_, {key: []})

        # Unknown method
        if is_notification:
            return None
        return _err(id_, _METHOD_NOT_FOUND, f"Method not found: {method!r}")

    except Exception as exc:  # noqa: BLE001
        if is_notification:
            return None
        return _err(id_, _INTERNAL_ERROR, "Internal error", str(exc))


# ---------------------------------------------------------------------------
# stdio transport
# ---------------------------------------------------------------------------


def run_stdio() -> None:
    """Read newline-delimited JSON from stdin, write responses to stdout.

    Suitable for Claude Desktop's ``stdio`` MCP configuration.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _err(None, _PARSE_ERROR, "Parse error", str(exc))
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# SSE transport (FastAPI sub-application)
# ---------------------------------------------------------------------------


def build_mcp_app():  # type: ignore[return]  # returns a Starlette app
    """Return a minimal Starlette ASGI app that speaks MCP over SSE.

    Mount it in the main FastAPI app::

        from app.mcp.server import build_mcp_app
        app.mount("/mcp", build_mcp_app())

    The SSE endpoint is at ``GET /mcp/sse``;  the client posts messages to
    ``POST /mcp/message`` and receives responses on the SSE stream.

    This is a skeleton: the channel plumbing (asyncio.Queue per connection)
    is in place but the SSE event-stream writer is left as a TODO so this
    file can be merged before the SSE transport is wired up end-to-end.
    """
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response
        from starlette.routing import Route
    except ImportError as exc:
        raise RuntimeError(
            "Starlette is required for the SSE transport. "
            "It is bundled with FastAPI — ensure fitwar-backend is installed."
        ) from exc

    async def message_endpoint(request: Request) -> Response:
        """Accept a JSON-RPC message and return the response synchronously.

        A production SSE implementation would push the response onto the
        client's SSE channel instead of returning it here, but the
        synchronous round-trip is correct for the ``tools/call`` flow and
        keeps the skeleton dependency-free.
        """
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse(
                _err(None, _PARSE_ERROR, "Could not parse JSON body"),
                status_code=400,
            )
        response = handle_request(body)
        if response is None:
            return Response(status_code=204)
        return JSONResponse(response)

    async def health_endpoint(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER_INFO})

    return Starlette(
        routes=[
            Route("/message", message_endpoint, methods=["POST"]),
            Route("/health", health_endpoint, methods=["GET"]),
        ]
    )


if __name__ == "__main__":
    run_stdio()

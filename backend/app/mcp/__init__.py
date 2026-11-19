"""FitWar MCP (Model Context Protocol) server package.

Exposes a subset of FitWar's read-only domain logic as MCP *tools* so that
AI assistants (e.g. Claude via claude.ai/settings or the Anthropic SDK) can
query live game state without direct database access.

Architecture notes
------------------
- The MCP layer is **read-only**. Mutations still go through the REST API so
  all existing auth, rate-limiting and audit trails apply unchanged.
- Tools call the same domain functions that the REST handlers call — no
  business logic lives here.
- The server is an *optional* mount: set ``MCP_ENABLED=true`` to attach it
  to the FastAPI app under ``/mcp``.

Usage (stdio transport, for local dev / Claude Desktop)::

    python -m app.mcp.server

Usage (SSE transport, mounted in FastAPI)::

    # In app/main.py the lifespan attaches this when MCP_ENABLED=true.
    from app.mcp.server import build_mcp_app
    app.mount("/mcp", build_mcp_app())
"""

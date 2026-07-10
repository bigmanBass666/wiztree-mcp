"""wiztree-mcp MCP server.

Creates the FastMCP instance, manages database lifecycle,
and registers all tools via the tool modules.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from wiztree_mcp.database import Database, get_db_path

logger = logging.getLogger(__name__)

# ── Server context ───────────────────────────────────────────────────

# Global singleton for the DB connection (accessed via lifespan context)
_db: Database | None = None


def get_db() -> Database:
    """Get the current Database instance from the server context.

    Must be called within a request context (after lifespan started).
    """
    if _db is None:
        raise RuntimeError("Database not initialized (lifespan not started)")
    return _db


# ── Lifespan ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(mcp: FastMCP) -> AsyncIterator[dict]:
    """Manage the database connection lifecycle.

    Opens the SQLite DB on startup, closes on shutdown.
    Yields an empty context dict (use get_db() in tools).
    """
    global _db
    db_path = get_db_path()
    logger.info("Opening database: %s", db_path)
    _db = Database(db_path)
    try:
        yield {}
    finally:
        logger.info("Closing database")
        _db.close()
        _db = None


# ── FastMCP instance ─────────────────────────────────────────────────

mcp = FastMCP(
    "wiztree-mcp",
    instructions="WizTree-based disk analysis MCP server. "
    "Scan drives, query disk usage, search paths, compare scans, "
    "and visualize file system data.",
    lifespan=lifespan,
)


# ── Tool registration ────────────────────────────────────────────────

# Import tool modules to register their @mcp.tool() decorated functions.
# Each module imports `mcp` from this module and decorates its functions.
from wiztree_mcp.tools import scan  # noqa: F401, E402
from wiztree_mcp.tools import query  # noqa: F401, E402
from wiztree_mcp.tools import analysis  # noqa: F401, E402
from wiztree_mcp.tools import compare  # noqa: F401, E402
from wiztree_mcp.tools import manage  # noqa: F401, E402


# ── Entry point ──────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server (STDIO transport)."""
    # Configure our logger to stderr (STDIO protocol: never write to stdout)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(handler)

    logger.info("Starting wiztree-mcp server (STDIO)")
    mcp.run(transport="stdio")
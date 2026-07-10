"""wiztree-mcp tools package.

Each module registers its tools via the @mcp.tool() decorator.
Import from server.py to ensure all tools are registered.
"""

from wiztree_mcp.tools import scan, query, analysis, compare, manage

__all__ = ["scan", "query", "analysis", "compare", "manage"]
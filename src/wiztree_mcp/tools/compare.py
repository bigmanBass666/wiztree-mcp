"""Compare tool: compare_scans."""

from __future__ import annotations

import logging
from typing import Optional

from mcp.server.fastmcp import Context as MCPContext

from wiztree_mcp import server
from wiztree_mcp.tools.query import _format_size

logger = logging.getLogger(__name__)


@server.mcp.tool()
async def compare_scans(
    scan_id_before: int,
    scan_id_after: int,
    ctx: MCPContext,
    limit: int = 20,
) -> str:
    """Compare two scans of the same drive to see what changed.

    Use this to measure cleanup results, track growth over time, or
    identify which directories changed the most between two points.

    Args:
        scan_id_before: The earlier scan ID (the "before" snapshot).
        scan_id_after: The later scan ID (the "after" snapshot).
        limit: Number of top changes to show (default 20, max 100).
        ctx: MCP context (injected automatically).

    Returns:
        Comparison report with capacity changes and top growth/shrink paths.
    """
    if limit > 100:
        limit = 100
    db = server.get_db()
    result = db.compare_scans(scan_id_before, scan_id_after, limit=limit)

    if result is None:
        return (
            f"Error: scan #{scan_id_before} or #{scan_id_after} not found. "
            "Use list_scans to find valid scan IDs."
        )

    delta_str = _format_size(abs(result["size_delta"]))
    delta_sign = "+" if result["size_delta"] >= 0 else "-"
    free_delta_str = _format_size(abs(result["free_delta"]))
    free_sign = "+" if result["free_delta"] >= 0 else "-"

    lines = [
        f"🔄 Scan Comparison: {result['drive']}",
        f"   Before: #{scan_id_before} | After: #{scan_id_after}",
        f"",
        f"   {'':>20}  {'Before':>12}  {'After':>12}  {'Delta':>12}",
        f"   {'Used Space':>20}  {_format_size(result['size_before']):>12}  "
        f"{_format_size(result['size_after']):>12}  {delta_sign}{delta_str:>11}",
        f"   {'Free Space':>20}  {_format_size(result['free_before']):>12}  "
        f"{_format_size(result['free_after']):>12}  {free_sign}{free_delta_str:>11}",
        "",
    ]

    if result.get("top_growth"):
        lines.append(f"📈 Top {len(result['top_growth'])} Growth:")
        lines.append(f"   {'Delta':>12}  {'Path'}")
        for g in result["top_growth"]:
            delta = _format_size(g["delta"])
            lines.append(f"   {delta:>12}  {g['path']}")

    if result.get("top_shrink"):
        lines.append(f"\n📉 Top {len(result['top_shrink'])} Shrinkage:")
        lines.append(f"   {'Delta':>12}  {'Path'}")
        for s in result["top_shrink"]:
            delta = _format_size(s["delta"])
            lines.append(f"   {delta:>12}  {s['path']}")

    if not result.get("top_growth") and not result.get("top_shrink"):
        lines.append("   No significant path-level changes detected.")

    return "\n".join(lines)
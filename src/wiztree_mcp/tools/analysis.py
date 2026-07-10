"""Analysis tools: file_type_summary, large_old_files."""

from __future__ import annotations

import logging
from typing import Optional

from mcp.server.fastmcp import Context as MCPContext

from wiztree_mcp import server
from wiztree_mcp.tools.query import _format_size

logger = logging.getLogger(__name__)


@server.mcp.tool()
async def file_type_summary(
    scan_id: int,
    ctx: MCPContext,
    limit: int = 30,
) -> str:
    """Summarize disk usage by file extension type.

    Groups all files by their extension and returns a ranked list of
    which file types consume the most space.

    Args:
        scan_id: The scan ID.
        limit: Number of extensions to show (default 30, max 100).
        ctx: MCP context (injected automatically).

    Returns:
        Ranked table of file extensions by total size.
    """
    if limit > 100:
        limit = 100
    db = server.get_db()
    rows = db.file_type_summary(scan_id, limit=limit)

    if not rows:
        return f"No file data found for scan #{scan_id}."

    total_all = sum(r["total_size"] for r in rows)

    lines = [
        f"📄 File Type Summary (scan #{scan_id})",
        f"   {'Size':>12}  {'%':>5}  {'Files':>8}  {'Extension'}",
        f"   {'-'*12}  {'-'*5}  {'-'*8}  {'-'*30}",
    ]

    for r in rows:
        size_str = _format_size(r["total_size"])
        pct = (r["total_size"] / total_all * 100) if total_all > 0 else 0
        lines.append(
            f"   {size_str:>12}  {pct:>4.1f}%  {r['file_count']:>8,}  .{r['extension']}"
        )

    lines.append(f"\n   Total accounted: {_format_size(total_all)}")

    return "\n".join(lines)


@server.mcp.tool()
async def large_old_files(
    scan_id: int,
    ctx: MCPContext,
    older_than_days: int = 180,
    min_size_mb: int = 100,
    limit: int = 50,
) -> str:
    """Find files that are both large and haven't been modified recently.

    These are prime candidates for cleanup — files taking up significant
    space that haven't been touched in a long time.

    Args:
        scan_id: The scan ID.
        older_than_days: Minimum age in days (default 180, ~6 months).
        min_size_mb: Minimum file size in MB (default 100).
        limit: Maximum results (default 50, max 200).
        ctx: MCP context (injected automatically).

    Returns:
        List of large, old files sorted by size descending.
    """
    if limit > 200:
        limit = 200
    db = server.get_db()
    min_size_bytes = min_size_mb * 1024 * 1024
    rows = db.large_old_files(
        scan_id,
        older_than_days=older_than_days,
        min_size=min_size_bytes,
        limit=limit,
    )

    if not rows:
        return (
            f"No files >{min_size_mb} MB modified more than "
            f"{older_than_days} days ago in scan #{scan_id}."
        )

    lines = [
        f"⏰ Large & Old Files (scan #{scan_id})",
        f"   Criteria: >{_format_size(min_size_bytes)}, "
        f"unmodified >{older_than_days} days",
        f"   {'Size':>12}  {'Last Modified':>16}  {'Path'}",
        f"   {'-'*12}  {'-'*16}  {'-'*70}",
    ]

    for r in rows:
        size_str = _format_size(r["size"])
        modified = (r["modified"] or "")[:16]
        lines.append(f"   {size_str:>12}  {modified:>16}  {r['path']}")

    return "\n".join(lines)
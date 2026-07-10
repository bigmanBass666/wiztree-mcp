"""Management tools: list_scans, get_treemap, cleanup_scans."""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from mcp.server.fastmcp import Context as MCPContext
from mcp.types import ImageContent

from wiztree_mcp import server
from wiztree_mcp.tools.query import _format_size

logger = logging.getLogger(__name__)


@server.mcp.tool()
async def list_scans(ctx: MCPContext) -> str:
    """List all previous disk scans stored in the database.

    Returns a table with scan ID, drive, label, scan time, and capacity info.
    Use this to find scan IDs for other tools like disk_summary or top_entries.

    Args:
        ctx: MCP context (injected automatically).

    Returns:
        Formatted list of all scans.
    """
    db = server.get_db()
    scans = db.list_scans()

    if not scans:
        return "No scans found. Use scan_disk to perform your first scan."

    lines = [
        f"📋 Scan History ({len(scans)} scans)",
        f"   {'ID':>3}  {'Drive':>6}  {'Label':>20}  {'Scanned At':>20}  "
        f"{'Used':>10}  {'Free':>10}",
        f"   {'-'*3}  {'-'*6}  {'-'*20}  {'-'*20}  {'-'*10}  {'-'*10}",
    ]

    for scan in scans:
        used = _format_size(scan.used_space) if scan.used_space else "N/A"
        free = _format_size(scan.free_space) if scan.free_space else "N/A"
        label = (scan.label or "")[:20] if scan.label else ""
        lines.append(
            f"   #{scan.id:<2}  {scan.drive:>6}  {label:>20}  "
            f"{scan.scanned_at:>20}  {used:>10}  {free:>10}"
        )

    return "\n".join(lines)


@server.mcp.tool()
async def get_treemap(scan_id: int, ctx: MCPContext) -> ImageContent:
    """Get a treemap visualization image for a scan (if generated during scan).

    Note: treemap images are only available if the scan was run with
    treemap=True in scan_disk.

    Args:
        scan_id: The scan ID to retrieve the treemap for.
        ctx: MCP context (injected automatically).

    Returns:
        PNG image content of the treemap visualization.
    """
    db = server.get_db()
    scan = db.get_scan(scan_id)
    if scan is None:
        return ImageContent(
            type="image",
            data="",
            mimeType="image/png",
        )

    # Look for treemap file in the data directory
    data_dir = os.environ.get(
        "WIZTREE_MCP_DATA_DIR",
        os.path.expanduser("~/.local/share/wiztree-mcp"),
    )

    # Search for matching treemap PNG files
    safe_name = scan.drive.replace(":", "").replace("\\", "_").replace("/", "_")
    if os.path.isdir(data_dir):
        for fname in os.listdir(data_dir):
            if fname.startswith(f"scan_{safe_name}_") and fname.endswith(".png"):
                fpath = os.path.join(data_dir, fname)
                with open(fpath, "rb") as f:
                    img_bytes = f.read()
                return ImageContent(
                    type="image",
                    data=base64.b64encode(img_bytes).decode("ascii"),
                    mimeType="image/png",
                )

    # No treemap found
    return ImageContent(
        type="image",
        data="",
        mimeType="image/png",
    )


@server.mcp.tool()
async def cleanup_scans(
    ctx: MCPContext,
    keep_latest: int = 5,
) -> str:
    """Remove older scans from the database to free up space.

    Keeps the N most recent scans and deletes everything older.
    Entries are cascade-deleted when their parent scan is removed.

    Args:
        keep_latest: Number of most recent scans to keep (default 5, min 1).
        ctx: MCP context (injected automatically).

    Returns:
        Report of which scans were deleted.
    """
    if keep_latest < 1:
        keep_latest = 1

    db = server.get_db()
    deleted_ids = db.cleanup_scans(keep_latest=keep_latest)

    if not deleted_ids:
        count = db.count_scans()
        return f"No scans to clean up. Database has {count} scan(s) (≤ {keep_latest})."

    return (
        f"🧹 Cleaned up {len(deleted_ids)} old scan(s): "
        f"IDs {', '.join(f'#{i}' for i in deleted_ids)}\n"
        f"Kept the {keep_latest} most recent scans."
    )
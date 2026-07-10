"""Query tools: disk_summary, top_entries, search_paths, drill_down."""

from __future__ import annotations

import json
import logging
from typing import Optional

from mcp.server.fastmcp import Context as MCPContext

from wiztree_mcp import server

logger = logging.getLogger(__name__)


@server.mcp.tool()
async def disk_summary(
    scan_id: int,
    ctx: MCPContext,
    top_n: int = 20,
) -> str:
    """Get a detailed summary of a disk scan.

    Returns drive info, capacity, total files/folders, and the top N
    largest files and folders.

    Args:
        scan_id: The scan ID (use list_scans to find available scans).
        top_n: Number of top files and folders to include (default 20, max 100).
        ctx: MCP context (injected automatically).

    Returns:
        Formatted summary string.
    """
    if top_n > 100:
        top_n = 100
    db = server.get_db()
    summary = db.get_summary(scan_id, top_n=top_n)

    if "error" in summary:
        return summary["error"]

    lines = [
        f"📊 Disk Summary — {summary['drive']}",
        f"   Scan ID: #{scan_id}",
        f"   Scanned at: {summary['scanned_at']}",
        f"   Label: {summary.get('label', '(none)')}",
    ]

    if summary.get("total_size"):
        total_gb = summary["total_size"] / (1024**3)
        used_gb = summary["used_space"] / (1024**3) if summary.get("used_space") else 0
        free_gb = summary["free_space"] / (1024**3) if summary.get("free_space") else 0
        lines.append(f"   Capacity: {total_gb:.1f} GB total, "
                      f"{used_gb:.1f} GB used, {free_gb:.1f} GB free")

    lines.extend([
        f"   Total files: {summary['total_files']:,}",
        f"   Total folders: {summary['total_folders']:,}",
        "",
    ])

    if summary.get("top_files"):
        lines.append(f"🔝 Top {len(summary['top_files'])} Largest Files:")
        lines.append(f"   {'Size':>12}  {'Path'}")
        lines.append(f"   {'-'*12}  {'-'*60}")
        for entry in summary["top_files"]:
            size_str = _format_size(entry["size"])
            lines.append(f"   {size_str:>12}  {entry['path']}")

    if summary.get("top_folders"):
        lines.append(f"\n📁 Top {len(summary['top_folders'])} Largest Folders:")
        lines.append(f"   {'Size':>12}  {'Path'}")
        lines.append(f"   {'-'*12}  {'-'*60}")
        for entry in summary["top_folders"]:
            size_str = _format_size(entry["size"])
            lines.append(f"   {size_str:>12}  {entry['path']}")

    return "\n".join(lines)


@server.mcp.tool()
async def top_entries(
    scan_id: int,
    ctx: MCPContext,
    kind: str = "files",
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List the largest entries in a scan (files, folders, or both).

    Args:
        scan_id: The scan ID.
        kind: Entry type — "files" (default), "folders", or "all".
        limit: Number of entries to return (default 20, max 500).
        offset: Pagination offset (default 0).
        ctx: MCP context (injected automatically).

    Returns:
        Formatted table of entries sorted by size descending.
    """
    if limit > 500:
        limit = 500
    db = server.get_db()

    rows = db._query_entries(scan_id, kind=kind, limit=limit, offset=offset)

    if not rows:
        return f"No entries found for scan #{scan_id} with kind='{kind}'."

    kind_label = {"files": "Files", "folders": "Folders", "all": "Entries"}.get(kind, "Entries")
    lines = [
        f"🔝 Top {len(rows)} {kind_label} (scan #{scan_id})",
        f"   {'Size':>12}  {'Modified':>10}  {'Path'}" if any(r["modified"] for r in rows) else
        f"   {'Size':>12}  {'Path'}",
        f"   {'-'*12}  {'-'*70}",
    ]

    for r in rows:
        size_str = _format_size(r["size"])
        modified = r["modified"] or ""
        if modified:
            modified = modified[:10] if len(modified) > 10 else modified
        folder_mark = "📁 " if r["is_folder"] else "   "
        mod_part = f"  {modified:>10}" if modified else ""
        lines.append(f"   {size_str:>12}{mod_part}  {folder_mark}{r['path']}")

    return "\n".join(lines)


@server.mcp.tool()
async def search_paths(
    scan_id: int,
    query: str,
    ctx: MCPContext,
    kind: str = "all",
    limit: int = 50,
) -> str:
    """Search for paths in a scan by keyword.

    Useful for finding specific directories or files (e.g., "node_modules",
    "cache", "npm", "temp").

    Args:
        scan_id: The scan ID.
        query: Search keyword or path fragment (case-insensitive).
        kind: Entry type — "all" (default), "files", or "folders".
        limit: Maximum results to return (default 50, max 200).
        ctx: MCP context (injected automatically).

    Returns:
        Matching entries with total aggregate size.
    """
    if limit > 200:
        limit = 200
    db = server.get_db()
    result = db.search_paths(scan_id, query, kind=kind, limit=limit)

    matches = result["matches"]
    total_matches = result["total_matches"]
    total_size = result["total_size"]

    if not matches:
        return f"No matches for '{query}' in scan #{scan_id}."

    kind_label = {"files": "files", "folders": "folders", "all": "entries"}.get(kind, "entries")
    total_size_str = _format_size(total_size)

    lines = [
        f"🔍 Found {total_matches:,} matching {kind_label} for '{query}' "
        f"(total size: {total_size_str})",
        f"   Showing top {len(matches)}:",
        f"   {'Size':>12}  {'Path'}",
        f"   {'-'*12}  {'-'*70}",
    ]

    for m in matches:
        size_str = _format_size(m["size"])
        folder_mark = "📁 " if m["is_folder"] else "   "
        lines.append(f"   {size_str:>12}  {folder_mark}{m['path']}")

    if total_matches > limit:
        lines.append(
            f"\n   ... and {total_matches - limit} more matches. "
            "Use a more specific query to narrow results."
        )

    return "\n".join(lines)


@server.mcp.tool()
async def drill_down(
    scan_id: int,
    folder_path: str,
    ctx: MCPContext,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Browse the contents of a specific folder (drill down).

    Shows all entries inside the given folder path, sorted by size descending.
    Useful for interactively exploring large directories step by step.

    Args:
        scan_id: The scan ID.
        folder_path: The folder path to drill into (e.g., "C:\\Users",
                    "D:\\Projects\\src").
        limit: Number of entries to return (default 50, max 200).
        offset: Pagination offset for seeing more items.
        ctx: MCP context (injected automatically).

    Returns:
        List of sub-entries (files and folders) inside the given path.
    """
    if limit > 200:
        limit = 200
    db = server.get_db()
    entries = db.drill_down(scan_id, folder_path, limit=limit, offset=offset)

    if not entries:
        return f"No entries found inside '{folder_path}' in scan #{scan_id}."

    lines = [
        f"📁 Contents of: {folder_path}",
        f"   {'Size':>12}  {'Modified':>10}  {'Path'}",
        f"   {'-'*12}  {'-'*70}",
    ]

    for entry in entries:
        size_str = _format_size(entry["size"])
        modified = entry["modified"] or ""
        if modified:
            modified = modified[:10]
        folder_mark = "📁 " if entry["is_folder"] else "   "
        mod_part = f"  {modified:>10}" if modified else ""
        lines.append(f"   {size_str:>12}{mod_part}  {folder_mark}{entry['path']}")

    return "\n".join(lines)


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes >= 1024**4:
        return f"{size_bytes / 1024**4:.1f} TB"
    elif size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.1f} GB"
    elif size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"
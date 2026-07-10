"""scan_disk tool: scan a drive/folder with WizTree and import into SQLite."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Optional

from mcp.server.fastmcp import Context as MCPContext

from wiztree_mcp import server
from wiztree_mcp.csv_importer import import_csv, extract_capacity_info
from wiztree_mcp.wiztree_cli import run_scan, find_wiztree, get_version

logger = logging.getLogger(__name__)


@server.mcp.tool()
async def scan_disk(
    target_path: str,
    ctx: MCPContext,
    label: Optional[str] = None,
    max_depth: Optional[int] = None,
    export_folders: bool = True,
    export_files: bool = True,
    treemap: bool = False,
    timeout: int = 300,
) -> str:
    """Scan a drive or folder with WizTree and import results into the database.

    This is the primary data ingestion tool. It:
    1. Locates the WizTree CLI executable
    2. Runs WizTree to export CSV (and optional treemap PNG)
    3. Streams the CSV into SQLite (memory-efficient, <50 MB)
    4. Returns a scan summary

    After scanning, use other tools (disk_summary, top_entries, etc.) to query
    the results.

    Args:
        target_path: Drive or folder to scan (e.g., "C:", "D:\\Projects").
        label: Optional human-readable label for this scan (e.g., "Cleanup Prep").
        max_depth: Maximum folder depth to export (None = unlimited).
                  Use a small value like 5 to reduce CSV size for quick scans.
        export_folders: Include folder entries in the export.
        export_files: Include file entries in the export.
        treemap: Also generate a treemap PNG image alongside the CSV.
        timeout: Maximum seconds to wait for the WizTree scan to complete.
        ctx: MCP context (injected automatically).

    Returns:
        JSON string with scan result summary.
    """
    db = server.get_db()

    # 1. Check WizTree availability
    wiztree_path = find_wiztree()
    if wiztree_path is None:
        return (
            "Error: WizTree64.exe not found.\n"
            "Install WizTree from https://diskanalyzer.com/ or\n"
            "set the WIZTREE_PATH environment variable to the full path."
        )

    # 2. Generate temp CSV path
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = target_path.replace(":", "").replace("\\", "_").replace("/", "_")
    csv_dir = os.environ.get("WIZTREE_MCP_DATA_DIR", os.path.expanduser("~/.local/share/wiztree-mcp"))
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, f"scan_{safe_name}_{timestamp}.csv")

    treemap_path = None
    if treemap:
        treemap_path = os.path.join(
            csv_dir, f"scan_{safe_name}_{timestamp}.png"
        )

    # 3. Run WizTree
    logger.info("Starting WizTree scan: %s → %s", target_path, csv_path)

    wiztree_ver = get_version()
    try:
        result = run_scan(
            target_path=target_path,
            csv_path=csv_path,
            admin=True,
            sort_by=1,
            export_folders=export_folders,
            export_files=export_files,
            export_drive_capacity=True,
            max_depth=max_depth,
            treemap_path=treemap_path,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running WizTree scan: {e}"

    if result.returncode != 0:
        logger.warning("WizTree returned non-zero exit code: %d", result.returncode)

    if not os.path.isfile(csv_path):
        return f"Error: WizTree did not produce output CSV at {csv_path}"

    csv_size_mb = os.path.getsize(csv_path) / (1024 * 1024)
    logger.info("CSV exported: %s (%.1f MB)", csv_path, csv_size_mb)

    # 4. Extract drive capacity info from CSV
    capacity = extract_capacity_info(csv_path)

    # 5. Create scan record
    scanned_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    scan_id = db.insert_scan(
        drive=target_path,
        label=label,
        scanned_at=scanned_at,
        wiztree_ver=wiztree_ver,
        total_size=capacity.get("total_size"),
        free_space=capacity.get("free_space"),
        used_space=capacity.get("used_space"),
    )

    # 6. Import CSV into DB
    try:
        stats = import_csv(db, scan_id, csv_path)
    except Exception as e:
        logger.error("CSV import failed: %s", e)
        db.delete_scan(scan_id)
        return f"Error importing CSV: {e}"

    # 7. Build summary
    used_gb = (capacity.get("used_space", 0) or 0) / (1024**3)
    free_gb = (capacity.get("free_space", 0) or 0) / (1024**3)
    total_gb = (capacity.get("total_size", 0) or 0) / (1024**3)

    summary_parts = [
        f"✅ Scan complete: {target_path}",
        f"   Scan ID: #{scan_id}",
        f"   Scanned at: {scanned_at}",
        f"   CSV size: {csv_size_mb:.1f} MB",
        f"   Rows imported: {stats['rows']:,}",
        f"        Files: {stats['files']:,}",
        f"        Folders: {stats['folders']:,}",
    ]

    if total_gb > 0:
        summary_parts.append(
            f"   Capacity: {total_gb:.1f} GB total, "
            f"{used_gb:.1f} GB used, {free_gb:.1f} GB free"
        )

    if treemap_path and os.path.isfile(treemap_path):
        summary_parts.append(f"   Treemap saved: {treemap_path}")

    if stats["errors"] > 0:
        summary_parts.append(f"   ⚠ {stats['errors']} rows had import errors")

    summary_parts.append(
        "\n📊 Next steps: use disk_summary(scan_id={scan_id}) for a detailed overview, "
        "or top_entries(scan_id={scan_id}, kind='files') to see the largest files."
    )

    return "\n".join(summary_parts)
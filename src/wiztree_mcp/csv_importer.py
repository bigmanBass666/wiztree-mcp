"""CSV streaming parser that imports WizTree CSV data into SQLite.

Memory-efficient: reads one row at a time, inserts row-by-row into the DB.
No full CSV is kept in memory.
"""

from __future__ import annotations

import csv
import logging
import os
import re
from typing import Callable, Optional

from wiztree_mcp.database import Database

logger = logging.getLogger(__name__)

# ── Column name mappings (WizTree variants) ──────────────────────────

# Known WizTree column headers (English, Chinese, short forms)
COLUMN_MAP: dict[str, str] = {
    # English
    "file name": "path",
    "name": "path",
    "size": "size",
    "allocated": "allocated",
    "modified": "modified",
    "modified date": "modified",
    "files": "files",
    "folders": "folders",
    "attributes": "attributes",
    # Chinese (disk_scan project uses these)
    "文件名称": "path",
    "大小": "size",
    "分配": "allocated",
    "修改时间": "modified",
    "文件": "files",
    "文件夹": "folders",
    # Short forms
    "path": "path",
    "date modified": "modified",
    "file count": "files",
    "folder count": "folders",
}

# Capacity columns (optional, from /exportdrivecapacity=1)
CAPACITY_COLS = {"drivecapacity", "freespace", "usedspace", "reservedspace"}


def find_header_offset(
    reader: csv.reader,
) -> tuple[Optional[list[str]], int]:
    """Skip WizTree preamble lines to find the CSV header row.

    WizTree CSV files start with 1-3 lines of preamble:
        Line 1 (comment): "生成由 WizTree 4.xx ..."
        Line 2 (empty or version): sometimes blank
        Line 3 (header): actual column names

    Returns (header_row, offset_lines_skipped).
    """
    for offset in range(20):  # safety cap
        try:
            row = next(reader)
        except StopIteration:
            return None, offset
        if not row:
            continue
        first = row[0].strip().lower()
        # Check if this looks like a header row
        if first in COLUMN_MAP or any(
            c in first for c in ("file name", "文件名称", "name", "path")
        ):
            # Normalize: strip BOM and whitespace
            normalized = [c.strip().strip('﻿') for c in row]
            return normalized, offset + 1
    return None, 20


def resolve_columns(
    header: list[str],
) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    """Map CSV column names to internal column indices.

    Returns (path_idx, size_idx, allocated_idx, modified_idx,
             files_idx, folders_idx, depth_idx).
    Any missing column gets None.
    """
    path_idx = size_idx = allocated_idx = modified_idx = None
    files_idx = folders_idx = depth_idx = None

    for i, col in enumerate(header):
        key = col.strip().lower()
        mapped = COLUMN_MAP.get(key)
        if mapped == "path":
            path_idx = i
        elif mapped == "size":
            size_idx = i
        elif mapped == "allocated":
            allocated_idx = i
        elif mapped == "modified":
            modified_idx = i
        elif mapped == "files":
            files_idx = i
        elif mapped == "folders":
            folders_idx = i

    return (path_idx, size_idx, allocated_idx, modified_idx,
            files_idx, folders_idx, depth_idx)


def parse_size(value: str) -> int:
    """Parse a size string to integer bytes.

    Handles empty, commas in numbers, and numeric strings.
    """
    if not value or not value.strip():
        return 0
    cleaned = value.strip().replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0


def compute_depth(path: str) -> int:
    """Compute directory depth from a path string."""
    # Count backslashes, ignoring trailing backslash
    path = path.rstrip("\\")
    if not path:
        return 0
    # Root "C:" has depth 0
    if path.endswith(":"):
        return 0
    return path.count("\\")


def is_folder_row(path: str, row: list[str], folders_idx: Optional[int]) -> bool:
    """Determine if a row represents a folder.

    WizTree folders end with \\ in the path column.
    Also check the 'folders' column if available.
    """
    if path.endswith("\\"):
        return True
    if folders_idx is not None and folders_idx < len(row):
        val = row[folders_idx].strip()
        if val and val != "0":
            return True
    return False


def import_csv(
    db: Database,
    scan_id: int,
    csv_path: str,
    *,
    on_progress: Optional[Callable[[int, int], None]] = None,
    batch_size: int = 5000,
) -> dict:
    """Stream-import a WizTree CSV file into the database.

    Args:
        db: Database instance.
        scan_id: Target scan ID for the imported entries.
        csv_path: Path to the WizTree CSV file.
        on_progress: Optional callback (rows_processed, total_estimated).
        batch_size: Commit interval (rows per transaction commit).

    Returns:
        Dict with import stats (rows, files, folders, errors).
    """
    stats: dict = {"rows": 0, "files": 0, "folders": 0, "errors": 0}
    file_size = os.path.getsize(csv_path)

    logger.info("Importing CSV: %s (%d bytes)", csv_path, file_size)

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)

        # Find the header row
        header = find_header_offset(reader)
        if header is None:
            raise ValueError(f"Could not find CSV header in {csv_path}")
        header_row, skipped = header

        # Resolve column indices
        col_idxs = resolve_columns(header_row)
        path_idx, size_idx, allocated_idx, modified_idx, files_idx, folders_idx, depth_idx = col_idxs

        if path_idx is None:
            raise ValueError(f"No 'path' column found in CSV header: {header_row}")
        if size_idx is None:
            raise ValueError(f"No 'size' column found in CSV header: {header_row}")

        # Stream rows into DB
        rows_in_batch = 0

        with db.begin_bulk_insert():
            for row in reader:
                if not row or not row[0].strip():
                    continue

                path = row[path_idx].strip()
                if not path:
                    continue

                size = parse_size(row[size_idx] if size_idx < len(row) else "")
                allocated = (
                    parse_size(row[allocated_idx])
                    if allocated_idx is not None and allocated_idx < len(row)
                    else 0
                )
                modified = (
                    row[modified_idx].strip()
                    if modified_idx is not None and modified_idx < len(row)
                    else None
                )
                if modified == "":
                    modified = None

                is_folder = is_folder_row(path, row, folders_idx)
                files_val = (
                    parse_size(row[files_idx])
                    if files_idx is not None and files_idx < len(row)
                    else None
                )
                folders_val = (
                    parse_size(row[folders_idx])
                    if folders_idx is not None and folders_idx < len(row)
                    else None
                )
                depth = compute_depth(path)

                try:
                    db.insert_entry(
                        scan_id=scan_id,
                        path=path,
                        size=size,
                        allocated=allocated,
                        modified=modified,
                        is_folder=is_folder,
                        files=files_val,
                        folders=folders_val,
                        depth=depth,
                    )
                except Exception as e:
                    stats["errors"] += 1
                    logger.warning("Row import error at row %d: %s", stats["rows"] + 1, e)
                    continue

                stats["rows"] += 1
                if is_folder:
                    stats["folders"] += 1
                else:
                    stats["files"] += 1
                rows_in_batch += 1

                # Periodic commit
                if rows_in_batch >= batch_size:
                    db.conn.commit()
                    rows_in_batch = 0

                # Progress callback (rough estimate)
                if on_progress and stats["rows"] % 10000 == 0:
                    on_progress(stats["rows"], 0)

        # Final commit
        db.conn.commit()

    logger.info(
        "Import complete: %d rows (%d files, %d folders, %d errors)",
        stats["rows"],
        stats["files"],
        stats["folders"],
        stats["errors"],
    )
    return stats


def extract_capacity_info(csv_path: str) -> dict:
    """Extract drive capacity info from the first data row of a CSV.

    WizTree with /exportdrivecapacity=1 outputs capacity cols.
    Returns dict with total_size, free_space, used_space or empty dict.
    """
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            # Find header
            header = find_header_offset(reader)
            if header is None:
                return {}
            header_row, _ = header

            # Check for capacity columns
            cap_idxs = {}
            for i, col in enumerate(header_row):
                key = col.strip().lower()
                if key in CAPACITY_COLS:
                    cap_idxs[key] = i

            if not cap_idxs:
                return {}

            # First data row (root entry) has capacity info
            for row in reader:
                if row and row[0].strip():
                    result = {}
                    if "drivecapacity" in cap_idxs:
                        result["total_size"] = parse_size(
                            row[cap_idxs["drivecapacity"]]
                        )
                    if "freespace" in cap_idxs:
                        result["free_space"] = parse_size(
                            row[cap_idxs["freespace"]]
                        )
                    if "usedspace" in cap_idxs:
                        result["used_space"] = parse_size(
                            row[cap_idxs["usedspace"]]
                        )
                    return result
    except Exception as e:
        logger.warning("Failed to extract capacity info: %s", e)
    return {}
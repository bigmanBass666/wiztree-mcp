"""SQLite database operations for wiztree-mcp.

Handles schema creation, CRUD for scans/entries, and bulk CSV import.
"""

from __future__ import annotations

import sqlite3
import contextlib
import logging
import os
from typing import Generator, Optional

from wiztree_mcp.models import (
    CompareResult,
    FileEntry,
    ScanMetadata,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    drive       TEXT NOT NULL,
    label       TEXT,
    scanned_at  TEXT NOT NULL,
    wiztree_ver TEXT,
    total_size  INTEGER,
    free_space  INTEGER,
    used_space  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    allocated   INTEGER NOT NULL DEFAULT 0,
    modified    TEXT,
    is_folder   INTEGER NOT NULL DEFAULT 0,
    files       INTEGER,
    folders     INTEGER,
    depth       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_entries_scan_id ON entries(scan_id);
CREATE INDEX IF NOT EXISTS idx_entries_path ON entries(path);
CREATE INDEX IF NOT EXISTS idx_entries_size ON entries(size);
CREATE INDEX IF NOT EXISTS idx_entries_is_folder ON entries(is_folder);
CREATE INDEX IF NOT EXISTS idx_entries_modified ON entries(modified);
CREATE INDEX IF NOT EXISTS idx_entries_scan_folder ON entries(scan_id, is_folder);
"""


def get_db_path(data_dir: str | None = None) -> str:
    """Resolve the SQLite database file path.

    Uses WIZTREE_MCP_DATA_DIR env var if set, otherwise defaults to
    a platform-appropriate data directory.
    """
    if data_dir is None:
        data_dir = os.environ.get("WIZTREE_MCP_DATA_DIR")
    if data_dir is None:
        # Default: ~/.local/share/wiztree-mcp/
        base = os.path.expanduser("~/.local/share/wiztree-mcp")
    else:
        base = data_dir
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "wiztree.db")


class Database:
    """Wraps a SQLite connection with schema management and queries."""

    def __init__(self, db_path: str, *, enable_wal: bool = True) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if enable_wal else None
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    # ── Scan CRUD ──────────────────────────────────────────────────────

    def insert_scan(
        self,
        drive: str,
        scanned_at: str,
        label: str | None = None,
        wiztree_ver: str | None = None,
        total_size: int | None = None,
        free_space: int | None = None,
        used_space: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO scans (drive, label, scanned_at, wiztree_ver,
                                  total_size, free_space, used_space)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (drive, label, scanned_at, wiztree_ver,
             total_size, free_space, used_space),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_scan(self, scan_id: int) -> Optional[ScanMetadata]:
        row = self._conn.execute(
            "SELECT * FROM scans WHERE id = ?", (scan_id,)
        ).fetchone()
        if row is None:
            return None
        return ScanMetadata(**dict(row))

    def list_scans(self) -> list[ScanMetadata]:
        rows = self._conn.execute(
            "SELECT * FROM scans ORDER BY created_at DESC"
        ).fetchall()
        return [ScanMetadata(**dict(r)) for r in rows]

    def delete_scan(self, scan_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def count_scans(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM scans").fetchone()
        return row["cnt"] if row else 0

    # ── Entries bulk import ────────────────────────────────────────────

    def begin_bulk_insert(self) -> contextlib._GeneratorContextManager:
        """Context manager wrapping a transaction for bulk entry insertion."""
        return self._conn  # sqlite3.Connection works as ctx manager

    def insert_entry(
        self,
        scan_id: int,
        path: str,
        size: int,
        allocated: int,
        modified: str | None,
        is_folder: bool,
        files: int | None,
        folders: int | None,
        depth: int | None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO entries (scan_id, path, size, allocated, modified,
                                    is_folder, files, folders, depth)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (scan_id, path, size, allocated, modified,
             1 if is_folder else 0, files, folders, depth),
        )

    # ── Queries ────────────────────────────────────────────────────────

    def get_summary(self, scan_id: int, top_n: int = 20) -> dict:
        """Return a structured summary for a scan."""
        scan = self.get_scan(scan_id)
        if scan is None:
            return {"error": f"Scan #{scan_id} not found"}

        total_files = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM entries WHERE scan_id=? AND is_folder=0",
            (scan_id,),
        ).fetchone()["cnt"]

        total_folders = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM entries WHERE scan_id=? AND is_folder=1",
            (scan_id,),
        ).fetchone()["cnt"]

        top_files = self._query_entries(scan_id, kind="files", limit=top_n)
        top_folders = self._query_entries(scan_id, kind="folders", limit=top_n)

        return {
            "drive": scan.drive,
            "label": scan.label,
            "scanned_at": scan.scanned_at,
            "total_size": scan.total_size,
            "free_space": scan.free_space,
            "used_space": scan.used_space,
            "total_files": total_files,
            "total_folders": total_folders,
            "top_files": [dict(r) for r in top_files],
            "top_folders": [dict(r) for r in top_folders],
        }

    def _query_entries(
        self,
        scan_id: int,
        kind: str = "files",
        limit: int = 50,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        if kind == "folders":
            is_folder = 1
        elif kind == "all":
            is_folder = None
        else:
            is_folder = 0

        if is_folder is not None:
            rows = self._conn.execute(
                """SELECT path, size, allocated, modified, is_folder, files, folders, depth
                   FROM entries
                   WHERE scan_id=? AND is_folder=?
                   ORDER BY size DESC LIMIT ? OFFSET ?""",
                (scan_id, is_folder, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT path, size, allocated, modified, is_folder, files, folders, depth
                   FROM entries
                   WHERE scan_id=?
                   ORDER BY size DESC LIMIT ? OFFSET ?""",
                (scan_id, limit, offset),
            ).fetchall()
        return rows

    def search_paths(
        self,
        scan_id: int,
        query: str,
        kind: str = "all",
        limit: int = 50,
    ) -> list[dict]:
        like_pattern = f"%{query}%"
        if kind == "folders":
            extra = "AND is_folder=1"
        elif kind == "files":
            extra = "AND is_folder=0"
        else:
            extra = ""

        rows = self._conn.execute(
            f"""SELECT path, size, allocated, modified, is_folder, files, folders
                FROM entries
                WHERE scan_id=? AND path LIKE ? {extra}
                ORDER BY size DESC LIMIT ?""",
            (scan_id, like_pattern, limit),
        ).fetchall()

        # Also compute aggregate total size for matching entries
        total_row = self._conn.execute(
            f"""SELECT COUNT(*) as count, COALESCE(SUM(size),0) as total_size
                FROM entries
                WHERE scan_id=? AND path LIKE ? {extra}""",
            (scan_id, like_pattern),
        ).fetchone()

        return {
            "matches": [dict(r) for r in rows],
            "total_matches": total_row["count"],
            "total_size": total_row["total_size"],
        }

    def drill_down(
        self,
        scan_id: int,
        folder_path: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Get children of a given folder path."""
        # Ensure folder_path ends with separator for matching
        sep = "\\"
        if not folder_path.endswith(sep):
            folder_path += sep

        rows = self._conn.execute(
            """SELECT path, size, allocated, modified, is_folder, files, folders, depth
               FROM entries
               WHERE scan_id=? AND (path = ? OR path LIKE ?)
               ORDER BY size DESC LIMIT ? OFFSET ?""",
            (scan_id, folder_path.rstrip(sep), f"{folder_path}%", limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def file_type_summary(
        self,
        scan_id: int,
        limit: int = 30,
    ) -> list[dict]:
        """Aggregate file usage by extension (files only)."""
        rows = self._conn.execute(
            """SELECT
                   CASE
                       WHEN INSTR(path, '.') > 0 THEN
                           SUBSTR(path, INSTR(path, '.') + 1)
                       ELSE '(no extension)'
                   END as extension,
                   COUNT(*) as file_count,
                   COALESCE(SUM(size), 0) as total_size,
                   COALESCE(SUM(allocated), 0) as total_allocated
               FROM entries
               WHERE scan_id=? AND is_folder=0
               GROUP BY extension
               ORDER BY total_size DESC
               LIMIT ?""",
            (scan_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def large_old_files(
        self,
        scan_id: int,
        older_than_days: int = 180,
        min_size: int = 100 * 1024 * 1024,  # 100 MB
        limit: int = 50,
    ) -> list[dict]:
        """Find files that are both large and old."""
        rows = self._conn.execute(
            """SELECT path, size, allocated, modified
               FROM entries
               WHERE scan_id=?
                 AND is_folder=0
                 AND size >= ?
                 AND modified IS NOT NULL
                 AND modified < date('now', ?)
               ORDER BY size DESC
               LIMIT ?""",
            (scan_id, min_size, f"-{older_than_days} days", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def compare_scans(
        self,
        scan_id_before: int,
        scan_id_after: int,
        limit: int = 20,
    ) -> Optional[dict]:
        """Compare two scans of the same drive."""
        before = self.get_scan(scan_id_before)
        after = self.get_scan(scan_id_after)
        if before is None or after is None:
            return None

        # TOP growth: entries in after that are bigger or new
        growth = self._conn.execute(
            """SELECT
                   COALESCE(a.path, b.path) as path,
                   COALESCE(a.size, 0) - COALESCE(b.size, 0) as delta
               FROM
                   (SELECT path, size FROM entries WHERE scan_id=?) a
                   FULL OUTER JOIN
                   (SELECT path, size FROM entries WHERE scan_id=?) b
                   ON a.path = b.path
               WHERE COALESCE(a.size, 0) - COALESCE(b.size, 0) > 0
               ORDER BY delta DESC
               LIMIT ?""",
            (scan_id_after, scan_id_before, limit),
        ).fetchall()

        # TOP shrink
        shrink = self._conn.execute(
            """SELECT
                   COALESCE(a.path, b.path) as path,
                   COALESCE(b.size, 0) - COALESCE(a.size, 0) as delta
               FROM
                   (SELECT path, size FROM entries WHERE scan_id=?) a
                   FULL OUTER JOIN
                   (SELECT path, size FROM entries WHERE scan_id=?) b
                   ON a.path = b.path
               WHERE COALESCE(b.size, 0) - COALESCE(a.size, 0) > 0
               ORDER BY delta DESC
               LIMIT ?""",
            (scan_id_after, scan_id_before, limit),
        ).fetchall()

        return {
            "drive": before.drive,
            "scan_before_id": scan_id_before,
            "scan_after_id": scan_id_after,
            "size_before": before.total_size,
            "size_after": after.total_size,
            "size_delta": (after.total_size or 0) - (before.total_size or 0),
            "free_before": before.free_space,
            "free_after": after.free_space,
            "free_delta": (after.free_space or 0) - (before.free_space or 0),
            "top_growth": [dict(r) for r in growth],
            "top_shrink": [dict(r) for r in shrink],
        }

    # ── Cleanup ────────────────────────────────────────────────────────

    def cleanup_scans(self, keep_latest: int = 5) -> list[int]:
        """Remove older scans beyond the N most recent.

        Returns list of deleted scan IDs.
        """
        # Find IDs to keep
        keep_ids = [
            r["id"]
            for r in self._conn.execute(
                "SELECT id FROM scans ORDER BY created_at DESC LIMIT ?",
                (keep_latest,),
            ).fetchall()
        ]

        if not keep_ids:
            return []

        placeholders = ",".join("?" for _ in keep_ids)
        doomed = self._conn.execute(
            f"SELECT id FROM scans WHERE id NOT IN ({placeholders})",
            keep_ids,
        ).fetchall()
        doomed_ids = [r["id"] for r in doomed]

        if doomed_ids:
            del_placeholders = ",".join("?" for _ in doomed_ids)
            self._conn.execute(
                f"DELETE FROM entries WHERE scan_id IN ({del_placeholders})",
                doomed_ids,
            )
            self._conn.execute(
                f"DELETE FROM scans WHERE id IN ({del_placeholders})",
                doomed_ids,
            )
            self._conn.commit()

        return doomed_ids

    def close(self) -> None:
        self._conn.close()
"""Data classes for wiztree-mcp."""

from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass(frozen=True)
class ScanMetadata:
    """Metadata for a single disk scan session."""

    id: int
    drive: str
    label: Optional[str]
    scanned_at: str
    wiztree_ver: Optional[str]
    total_size: Optional[int]
    free_space: Optional[int]
    used_space: Optional[int]
    created_at: str


@dataclasses.dataclass(frozen=True)
class FileEntry:
    """A single file or folder entry from a WizTree scan."""

    id: int
    scan_id: int
    path: str
    size: int
    allocated: int
    modified: Optional[str]
    is_folder: bool
    files: Optional[int]
    folders: Optional[int]
    depth: Optional[int]


@dataclasses.dataclass(frozen=True)
class ScanSummary:
    """Aggregated summary of a disk scan."""

    drive: str
    label: Optional[str]
    scanned_at: str
    total_size: int
    free_space: int
    used_space: int
    total_files: int
    total_folders: int
    top_files: list[FileEntry]
    top_folders: list[FileEntry]


@dataclasses.dataclass(frozen=True)
class CompareResult:
    """Result of comparing two scans."""

    scan_before_id: int
    scan_after_id: int
    drive: str
    size_before: int
    size_after: int
    size_delta: int
    free_before: int
    free_after: int
    free_delta: int
    top_growth: list[dict]
    top_shrink: list[dict]
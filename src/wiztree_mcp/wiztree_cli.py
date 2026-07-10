"""WizTree executable discovery and CLI invocation."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Common install locations on Windows
_DEFAULT_SEARCH_PATHS = [
    r"D:\apps\WizTree\WizTree64.exe",
    r"C:\Program Files\WizTree\WizTree64.exe",
    r"C:\Program Files (x86)\WizTree\WizTree64.exe",
]

# Environment variable override
_ENV_VAR = "WIZTREE_PATH"


@dataclass
class WizTreeResult:
    """Result of a WizTree scan execution."""

    csv_path: str
    treemap_path: Optional[str]
    returncode: int
    stdout: str
    stderr: str


def find_wiztree() -> Optional[str]:
    """Locate the WizTree64.exe executable.

    Checks (in order):
    1. WIZTREE_PATH environment variable
    2. Common install locations
    3. PATH lookup

    Returns absolute path to the exe, or None if not found.
    """
    # 1. Env var override
    env_path = os.environ.get(_ENV_VAR)
    if env_path:
        env_path = env_path.strip('"')
        if os.path.isfile(env_path):
            logger.info("Found WizTree via %s: %s", _ENV_VAR, env_path)
            return env_path
        logger.warning("WIZTREE_PATH set but file not found: %s", env_path)

    # 2. Common install paths
    for path in _DEFAULT_SEARCH_PATHS:
        if os.path.isfile(path):
            logger.info("Found WizTree at default path: %s", path)
            return path

    # 3. PATH lookup
    which = shutil_which("WizTree64.exe")
    if which:
        logger.info("Found WizTree via PATH: %s", which)
        return which

    logger.warning("WizTree64.exe not found in any search location")
    return None


def shutil_which(name: str) -> Optional[str]:
    """Cross-platform 'which' using os.environ PATH."""
    path_ext = os.environ.get("PATHEXT", "")
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(dir_path, name)
        if os.path.isfile(candidate):
            return candidate
        # Also try with extensions from PATHEXT
        for ext in path_ext.split(os.pathsep):
            candidate_ext = candidate + ext.lower()
            if os.path.isfile(candidate_ext):
                return candidate_ext
    return None


def run_scan(
    target_path: str,
    csv_path: str,
    *,
    admin: bool = True,
    sort_by: int = 1,
    export_folders: bool = True,
    export_files: bool = True,
    export_drive_capacity: bool = True,
    max_depth: Optional[int] = None,
    treemap_path: Optional[str] = None,
    treemap_width: int = 1920,
    treemap_height: int = 1080,
    timeout: int = 300,
) -> WizTreeResult:
    """Execute a WizTree scan.

    Args:
        target_path: Drive or folder to scan (e.g., "C:", "D:\\Projects").
        csv_path: Output CSV file path.
        admin: Enable admin mode for MFT scan (needed for full drives).
        sort_by: 0=name, 1=size desc, 2=allocated desc, 3=modified desc.
        export_folders: Include folder rows in CSV.
        export_files: Include file rows in CSV.
        export_drive_capacity: Include drive capacity columns.
        max_depth: Maximum folder depth (None = unlimited).
        treemap_path: Optional PNG output path for treemap image.
        treemap_width: Treemap image width in pixels.
        treemap_height: Treemap image height in pixels.
        timeout: Maximum seconds to wait for scan.

    Returns:
        WizTreeResult with output paths and exit info.

    Raises:
        FileNotFoundError: If WizTree executable is not found.
        subprocess.TimeoutExpired: If scan exceeds timeout.
    """
    exe_path = find_wiztree()
    if exe_path is None:
        searched = _DEFAULT_SEARCH_PATHS + ["PATH"]
        msg = (
            "WizTree64.exe not found. "
            f"Searched: {', '.join(searched)}\n"
            f"Set {_ENV_VAR} environment variable to the full path, "
            "or install WizTree from https://diskanalyzer.com/"
        )
        raise FileNotFoundError(msg)

    cmd = [
        exe_path,
        target_path,
        f'/export="{csv_path}"',
        f"/admin={1 if admin else 0}",
        f"/sortby={sort_by}",
        f"/exportfolders={1 if export_folders else 0}",
        f"/exportfiles={1 if export_files else 0}",
        f"/exportdrivecapacity={1 if export_drive_capacity else 0}",
    ]

    if max_depth is not None:
        cmd.append(f"/exportmaxdepth={max_depth}")

    if treemap_path:
        cmd.append(f'/treemapimagefile="{treemap_path}"')
        cmd.append(f"/treemapimagewidth={treemap_width}")
        cmd.append(f"/treemapimageheight={treemap_height}")

    logger.info("Running WizTree: %s", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if proc.returncode != 0:
        logger.warning(
            "WizTree exited with code %d: %s",
            proc.returncode,
            proc.stderr.strip(),
        )

    return WizTreeResult(
        csv_path=csv_path,
        treemap_path=treemap_path,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def get_version() -> Optional[str]:
    """Try to get the installed WizTree version."""
    exe_path = find_wiztree()
    if exe_path is None:
        return None
    try:
        result = subprocess.run(
            [exe_path, "/?"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Version info is typically in the first line of stderr or stdout
        for line in (result.stdout + result.stderr).splitlines():
            if "WizTree" in line:
                return line.strip()
    except Exception:
        pass
    return None
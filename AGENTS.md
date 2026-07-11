# wiztree-mcp

WizTree-based disk analysis MCP server. Scan drives, query disk usage, search paths, compare scans, and visualize file system data — all from Claude Code.

## Quick Start

```bash
pip install wiztree-mcp
# WizTree64.exe required on Windows — install from https://diskanalyzer.com/
```

Register in `.mcp.json`:
```json
{
  "mcpServers": {
    "wiztree": {
      "type": "stdio",
      "command": ".venv\\Scripts\\python",
      "args": ["-m", "wiztree_mcp"]
    }
  }
}
```

## Architecture

```
src/wiztree_mcp/
├── __init__.py
├── __main__.py       # Entry point: from server import main; main()
├── server.py         # FastMCP instance, lifespan, tool registration
├── database.py       # SQLite CRUD (scans + entries tables)
├── models.py         # Dataclasses (Scan, Entry, ScanType, EntryType)
├── csv_importer.py   # CSV parser → bulk INSERT into SQLite
├── wiztree_cli.py    # WizTree64.exe discovery & invocation
└── tools/
    ├── scan.py       # scan_disk — primary data ingestion
    ├── query.py      # disk_summary, top_entries, search_paths, drill_down
    ├── analysis.py   # file_type_summary, large_old_files
    ├── compare.py    # compare_scans — SQL FULL OUTER JOIN
    └── manage.py     # list_scans, get_treemap, cleanup_scans
```

## Tools (11 total)

### Data Ingestion
- `scan_disk(target, label?, max_depth?, export_folders?, export_files?, treemap?, timeout?)` — Scan with WizTree, import CSV into SQLite

### Query
- `disk_summary(scan_id, top_n?)` — Drive info + capacity + top files/folders
- `top_entries(scan_id, kind?, limit?, offset?)` — Largest files/folders
- `search_paths(scan_id, query, kind?, limit?)` — Keyword search
- `drill_down(scan_id, folder_path, limit?, offset?)` — Browse folder contents
- `file_type_summary(scan_id, limit?)` — Disk usage by extension
- `large_old_files(scan_id, older_than_days?, min_size_mb?, limit?)` — Cleanup candidates

### Comparison
- `compare_scans(scan_id_before, scan_id_after, limit?)` — SQL JOIN diff

### Management
- `list_scans()` — Available scans
- `get_treemap(scan_id)` — PNG treemap image
- `cleanup_scans(keep_latest?)` — Remove old scans

### Key technical facts
- WizTree64.exe is a GUI app on Windows; `subprocess.run()` with `STARTUPINFO` hides its window.
- Admin mode (`/admin=1`) is auto-enabled only for full drive scans (e.g., "C:"), not directories — avoids UAC hang.
- CSV import uses streaming (<50 MB memory).
- SQLite database is the single source of truth for all queries after import.
- On a scan, WizTree exports a CSV file; the server then parses and imports it into SQLite. The CSV file is kept as a cache.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
pyright
python -m wiztree_mcp
```

## CLAUDE.md Rules
- Write tests first for new features.
- Keep memory under 50 MB for CSV import.
- Use SQLite JOINs, not Python dicts, for cross-scan comparisons.
- All tools must use `@server.mcp.tool()` decorator from `server.py`.
- MCP tools communicate via stdio; log to stderr only.
- Window hiding: `STARTUPINFO.dwFlags = 0x0001; wShowWindow = 0`.
# wiztree-mcp

**WizTree-based disk analysis MCP server** — scan drives, query disk usage, search paths, compare snapshots, and visualize file system data, all through MCP tools.

```json
// Claude Code config
{
  "mcpServers": {
    "wiztree": {
      "command": "wiztree-mcp"
    }
  }
}
```

## Features

### 🗂️ Scan
- **`scan_disk`** — Scan a drive/folder with WizTree and import results into SQLite. Memory-efficient streaming (no full CSV in RAM).

### 📋 Query
- **`list_scans`** — List all previous scans
- **`disk_summary`** — Detailed overview (capacity, files, folders, top N)
- **`top_entries`** — Largest files/folders sorted by size
- **`drill_down`** — Browse a specific folder's contents

### 🔍 Search
- **`search_paths`** — Keyword/glob path search with aggregate size
- **`file_type_summary`** — Disk usage by file extension
- **`large_old_files`** — Find large files not modified recently

### 🔄 Compare
- **`compare_scans`** — Two-scan delta report (growth + shrinkage)

### 🛠️ Management
- **`get_treemap`** — Retrieve treemap visualization (if generated during scan)
- **`cleanup_scans`** — Prune old scans, keep only N recent

## Installation

```bash
pip install wiztree-mcp
```

Requires **Python 3.10+** and **WizTree** (free, [diskanalyzer.com](https://diskanalyzer.com/)).

### WizTree Setup

1. Install [WizTree](https://diskanalyzer.com/download) (64-bit)
2. Ensure `WizTree64.exe` is in PATH or at a standard install location, or set the `WIZTREE_PATH` environment variable:
   ```bash
   set WIZTREE_PATH=D:\apps\WizTree\WizTree64.exe
   ```

## Usage

### Start the server

```bash
wiztree-mcp
```

This starts the MCP server on STDIO — the standard transport for MCP hosts like Claude Code.

### Scan a drive

```python
# Via MCP tool (in Claude Code or any MCP host)
await mcp.call_tool("scan_disk", {"target_path": "C:"})
```

### Query results

```python
await mcp.call_tool("disk_summary", {"scan_id": 1})
await mcp.call_tool("top_entries", {"scan_id": 1, "kind": "files", "limit": 20})
await mcp.call_tool("search_paths", {"scan_id": 1, "query": "node_modules"})
await mcp.call_tool("drill_down", {"scan_id": 1, "folder_path": "C:\\Users"})
```

### Compare scans

```python
await mcp.call_tool("compare_scans", {
    "scan_id_before": 1,
    "scan_id_after": 2,
})
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `WIZTREE_PATH` | Path to `WizTree64.exe` (overrides auto-detection) |
| `WIZTREE_MCP_DATA_DIR` | Data directory for DB and exported CSVs (default: `~/.local/share/wiztree-mcp/`) |

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 MCP Host (Claude Code)          │
├─────────────────────────────────────────────────┤
│  STDIO transport ──── wiztree-mcp server        │
│                         │                       │
│  ┌──────────────────────┴──────────────────┐    │
│  │  FastMCP (mcp SDK)                     │    │
│  │  ├── 11 tools via @mcp.tool()          │    │
│  │  └── Lifespan (DB lifecycle)           │    │
│  ├────────────────────────────────────────┤    │
│  │  Database (SQLite)                     │    │
│  │  ├── scans table (metadata)            │    │
│  │  ├── entries table (files + folders)   │    │
│  │  └── 6 indexes for fast queries        │    │
│  ├────────────────────────────────────────┤    │
│  │  WizTree CLI                           │    │
│  │  └── WizTree64.exe /export=...         │    │
│  └────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**Key design decisions:**
- **CSV → SQLite streaming**: CSV is parsed row by row and inserted into SQLite. Never more than ~50 MB of RAM, regardless of CSV size.
- **SQL queries**: All tools use indexed SQL queries (O(log n)), not array iteration (O(n)).
- **Persistence**: Data survives server restarts. Cross-session comparison is a SQL JOIN.
- **Zero extra deps**: Only `mcp` SDK. `csv` and `sqlite3` are Python stdlib.

## Development

```bash
git clone https://github.com/onmokoworks/wiztree-mcp
cd wiztree-mcp
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -e .
python tests/test_db_quick.py
python tests/test_csv_importer.py
```

## Performance

| Metric | Before (TS) | After (Python + SQLite) |
|--------|-------------|------------------------|
| CSV parse (400 MB) | ~210 s, 1-2 GB RAM | ~30 s, <50 MB RAM |
| Queries | O(n) array scan | O(log n) SQL index |
| Persistence | None (in-memory cache) | SQLite permanent store |
| Cross-session compare | 2 CSVs fully loaded | SQL JOIN (milliseconds) |
| Startup | ~5 s (parse CSV) | ~50 ms (open DB) |
| Dependencies | csv-parse + zod + sdk | Only `mcp` (Python stdlib for CSV + SQLite) |

## License

MIT
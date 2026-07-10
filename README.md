# wiztree-mcp

**基于 WizTree 的磁盘分析 MCP 服务器** — 通过 MCP 工具扫描驱动器、查询磁盘使用情况、搜索路径、比较快照以及可视化文件系统数据。

```json
// Claude Code 配置
{
  "mcpServers": {
    "wiztree": {
      "command": "wiztree-mcp"
    }
  }
}
```

## 功能特性

### 🗂️ 扫描
- **`scan_disk`** — 用 WizTree 扫描驱动器/文件夹并将结果导入 SQLite。内存高效流式处理（无需将完整 CSV 加载到内存）。

### 📋 查询
- **`list_scans`** — 列出所有历史扫描记录
- **`disk_summary`** — 详细概览（容量、文件数、文件夹数、Top N）
- **`top_entries`** — 按大小排序的最大文件/文件夹
- **`drill_down`** — 浏览指定文件夹的内容

### 🔍 搜索
- **`search_paths`** — 关键字/通配符路径搜索，附带汇总大小
- **`file_type_summary`** — 按文件扩展名统计磁盘使用情况
- **`large_old_files`** — 查找长期未修改的大文件

### 🔄 比较
- **`compare_scans`** — 两次扫描的差异报告（增长 + 缩减）

### 🛠️ 管理
- **`get_treemap`** — 获取树图可视化（若扫描时已生成）
- **`cleanup_scans`** — 清理旧扫描，仅保留最近 N 次

## 安装

```bash
pip install wiztree-mcp
```

需要 **Python 3.10+** 和 **WizTree**（免费，[diskanalyzer.com](https://diskanalyzer.com/)）。

### WizTree 设置

1. 安装 [WizTree](https://diskanalyzer.com/download)（64 位）
2. 确保 `WizTree64.exe` 在 PATH 中或位于标准安装位置，或设置 `WIZTREE_PATH` 环境变量：
   ```bash
   set WIZTREE_PATH=D:\apps\WizTree\WizTree64.exe
   ```

## 使用

### 启动服务器

```bash
wiztree-mcp
```

这将在 STDIO 上启动 MCP 服务器——这是 Claude Code 等 MCP 主机的标准传输方式。

### 扫描驱动器

```python
# 通过 MCP 工具（在 Claude Code 或任意 MCP 主机中）
await mcp.call_tool("scan_disk", {"target_path": "C:"})
```

### 查询结果

```python
await mcp.call_tool("disk_summary", {"scan_id": 1})
await mcp.call_tool("top_entries", {"scan_id": 1, "kind": "files", "limit": 20})
await mcp.call_tool("search_paths", {"scan_id": 1, "query": "node_modules"})
await mcp.call_tool("drill_down", {"scan_id": 1, "folder_path": "C:\\Users"})
```

### 比较扫描

```python
await mcp.call_tool("compare_scans", {
    "scan_id_before": 1,
    "scan_id_after": 2,
})
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `WIZTREE_PATH` | `WizTree64.exe` 的路径（覆盖自动检测） |
| `WIZTREE_MCP_DATA_DIR` | 数据库和导出 CSV 的存储目录（默认：`~/.local/share/wiztree-mcp/`） |

## 架构

```
┌─────────────────────────────────────────────────┐
│                 MCP 主机 (Claude Code)           │
├─────────────────────────────────────────────────┤
│  STDIO 传输 ──── wiztree-mcp 服务器              │
│                         │                       │
│  ┌──────────────────────┴──────────────────┐    │
│  │  FastMCP (mcp SDK)                     │    │
│  │  ├── 11 个工具 via @mcp.tool()         │    │
│  │  └── Lifespan (DB 生命周期管理)        │    │
│  ├────────────────────────────────────────┤    │
│  │  数据库 (SQLite)                       │    │
│  │  ├── scans 表 (元数据)                 │    │
│  │  ├── entries 表 (文件 + 文件夹)        │    │
│  │  └── 6 个索引用于快速查询              │    │
│  ├────────────────────────────────────────┤    │
│  │  WizTree CLI                           │    │
│  │  └── WizTree64.exe /export=...         │    │
│  └────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**关键设计决策：**
- **CSV → SQLite 流式处理**：CSV 逐行解析并插入 SQLite。无论 CSV 多大，内存占用始终不超过 ~50 MB。
- **SQL 查询**：所有工具使用索引 SQL 查询（O(log n)），而非数组遍历（O(n)）。
- **持久化**：数据在服务器重启后仍然保留。跨会话比较即 SQL JOIN。
- **零额外依赖**：仅 `mcp` SDK。`csv` 和 `sqlite3` 均为 Python 标准库。

## 开发

```bash
git clone https://github.com/onmokoworks/wiztree-mcp
cd wiztree-mcp
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -e .
python tests/test_db_quick.py
python tests/test_csv_importer.py
```

## 性能

| 指标 | 之前 (TypeScript) | 之后 (Python + SQLite) |
|------|-------------------|------------------------|
| CSV 解析 (400 MB) | ~210 秒, 1-2 GB 内存 | ~30 秒, <50 MB 内存 |
| 查询 | O(n) 数组扫描 | O(log n) SQL 索引 |
| 持久化 | 无（内存缓存） | SQLite 永久存储 |
| 跨会话比较 | 完整加载 2 个 CSV | SQL JOIN（毫秒级） |
| 启动 | ~5 秒（解析 CSV） | ~50 毫秒（打开数据库） |
| 依赖项 | csv-parse + zod + sdk | 仅 `mcp`（CSV + SQLite 使用 Python 标准库） |

## 许可证

MIT
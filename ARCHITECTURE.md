# wiztree-mcp 架构设计

> 基于 WizTree CLI 的磁盘分析 MCP 服务器  
> 设计日期：2026-07-11  
> 状态：草稿

---

## 一、项目概述

### 1.1 定位

**wiztree-mcp** 是一个独立的 MCP 服务器，为 AI 助手提供磁盘空间分析能力。用户告诉它扫哪个盘，它存储分析结果，之后任何查询都毫秒级返回。

```
pip install wiztree-mcp
# 配置到 Claude Code：
# "mcpServers": { "wiztree": { "command": "wiztree-mcp" } }
```

### 1.2 设计原则（来自 MCP 设计哲学）

| 原则 | 在本项目中的体现 |
|------|----------------|
| **收敛而非选择** | 每个工具只做一件事，不做功能重叠的设计 |
| **可组合而非特定** | 工具是基本查询原语，不封装"一键清理"等高阶操作 |
| **稳定优于速度** | 工具接口设计需谨慎，一个工具名确定后不轻易改 |
| **实用优于纯粹** | 接受合理的工程权衡（如 CSV 批量导入快的方案即可，不追求理论最优） |

---

## 二、技术栈选型

### 2.1 语言：Python 3.10+

**选择理由：**

| 对比项 | Python | TypeScript（原项目） | Rust | Go |
|--------|--------|-------------------|------|-----|
| 内存效率 | 良好（~160 字节/行） | 差（~600 字节/行，UTF-16+对象开销） | 最优 | 良好 |
| CSV 解析速度 | 快（标准库 csv 边读边写 SQLite） | 慢（400MB/210 秒，纯 JS csv-parse） | 最快 | 快 |
| SQLite | 标准库内置，零依赖 | 需 better-sqlite3 编译原生模块 | 需 rusqlite | 需第三方包 |
| MCP SDK 成熟度 | Tier 1（官方维护） | Tier 1 | Tier 2 | Tier 1 |
| 数据管道生态 | 最优（pandas/numpy/sqlite3 原生支持） | 不擅长 | 不擅长 | 尚可 |
| 与 disk_scan 复用 | 可直接复用 analyze.py 分类逻辑 | 不可复用 | 不可复用 | 不可复用 |
| 交付速度 | 几天可用 | 快 | 数周 | 几天 |

**核心判断：** 这个项目的本质是 **数据管道**（CSV→清洗→SQLite→查询），这是 Python 最擅长的领域。MCP 的 Tier 1 官方 Python SDK 让协议处理零成本。

### 2.2 存储：SQLite 3

- Python 标准库 `sqlite3`，零外部依赖
- CSV 一次性导入 SQLite → 后续所有查询走 SQL 索引
- 同磁盘多次扫描自动追加，支持跨时间点对比
- 单文件数据库，方便备份和迁移

### 2.3 MCP 框架：FastMCP（`mcp` 包）

- Anthropic 官方维护，Tier 1 SDK
- 装饰器模式，Python 类型提示自动生成 JSON Schema
- 支持 Context 注入（日志、进度、Elicitation）
- 内建 Lifespan 管理（启动时打开 DB，关闭时关闭）
- STDIO 传输，零配置

### 2.4 依赖清单（最小化）

```toml
dependencies = [
    "mcp >= 1.2.0",
]
```

零额外依赖。`csv` 和 `sqlite3` 是 Python 标准库。

### 2.5 不选择的技术

| 技术 | 不选的理由 |
|------|-----------|
| pandas | 太重（~10MB 依赖），对大 CSV 不如 sqlite3 直接流式导入快 |
| numpy | 不需要数值计算 |
| httpx / aiohttp | STDIO 传输不需要 HTTP |
| Pydantic | FastMCP 已内建支持，不需要额外引入 |

---

## 三、项目结构

```
wiztree-mcp/
├── src/wiztree_mcp/
│   ├── __init__.py          # 包入口，export server 实例
│   ├── __main__.py          # python -m wiztree_mcp 支持
│   ├── server.py            # FastMCP 创建、工具注册
│   ├── database.py          # SQLite 操作层（建表、CRUD、导入）
│   ├── wiztree_cli.py       # WizTree 可执行文件查找与调用
│   ├── csv_importer.py      # CSV 解析→SQLite 导入
│   ├── models.py            # 数据类定义
│   └── tools/               # 工具按文件拆分
│       ├── __init__.py
│       ├── scan.py          # scan_disk
│       ├── query.py         # disk_summary, top_entries, search_paths, drill_down
│       ├── analysis.py      # file_type_summary, large_old_files
│       ├── compare.py       # compare_scans
│       └── manage.py        # list_scans, get_treemap, cleanup_scans
├── tests/
│   ├── test_database.py
│   ├── test_csv_importer.py
│   ├── test_tools.py
│   └── fixtures/            # 测试用 CSV 样本
├── docs/
│   ├── mcp-full-docs-research.md
│   └── mcp-build-research.md
├── pyproject.toml
└── README.md
```

---

## 四、SQLite 数据库设计

### 4.1 表结构

```sql
-- 扫描元数据
CREATE TABLE scans (
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

-- 文件系统条目（每次扫描的每一行）
CREATE TABLE entries (
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

-- 索引
CREATE INDEX idx_entries_scan_id ON entries(scan_id);
CREATE INDEX idx_entries_path ON entries(path);
CREATE INDEX idx_entries_size ON entries(size);
CREATE INDEX idx_entries_is_folder ON entries(is_folder);
CREATE INDEX idx_entries_modified ON entries(modified);
CREATE INDEX idx_entries_scan_folder ON entries(scan_id, is_folder);
```

### 4.2 设计要点

- **entries 表**存储磁盘上每个文件和文件夹的信息，WizTree CSV 的每一行对应一条记录
- **scan_id 外键**关联到 scans 表，支持多时间点对比
- **索引策略**：scan_id 隔离不同扫描，size 用于 TOP N 查询，path 用于搜索，modified 用于时间筛选
- **depth 字段**预处理路径深度，加速 drill_down 下钻查询
- **CASCADE 删除**删除扫描时自动清理所有条目

### 4.3 与 disk_scan 的关系

WizTree CSV 的扇出式目录结构（每行一个条目）不适合直接映射到 disk_scan 的 Top 200 目录快照。新系统通过 SQL 查询可灵活生成等价数据：

```sql
-- 等价的 Top 200 目录快照
SELECT path, size, allocated, files, folders
FROM entries
WHERE scan_id = ? AND is_folder = 1 AND depth >= 1
ORDER BY size DESC LIMIT 200;
```

disk_scan 的 `session_manager.py` 仍可继续使用，它可以直接读取 SQLite 作为数据源。

---

## 五、工具设计

### 5.1 工具清单

| # | 工具名 | 用途 | 输入参数 | 输出 |
|---|--------|------|---------|------|
| 1 | `scan_disk` | 扫描磁盘并导入 SQLite | target_path + 可选参数 | 扫描摘要 JSON |
| 2 | `list_scans` | 列出扫描历史 | 无 | 扫描列表表格 |
| 3 | `disk_summary` | 磁盘概况 | scan_id + top_n | JSON 摘要 |
| 4 | `top_entries` | 最大条目 TOP N | scan_id + kind + limit | 表格 |
| 5 | `search_paths` | 路径搜索 | scan_id + query + kind + limit | 匹配条目 + 总大小 |
| 6 | `drill_down` | 目录下钻 | scan_id + folder_path + limit | 子条目表格 |
| 7 | `file_type_summary` | 扩展名汇总 | scan_id + limit | 扩展名排名表格 |
| 8 | `large_old_files` | 老旧大文件 | scan_id + older_than_days + min_size + limit | 匹配文件表格 |
| 9 | `compare_scans` | 两次扫描对比 | scan_id_before + scan_id_after | 增长/缩减对比 |
| 10 | `get_treemap` | 获取 Treemap PNG | scan_id | PNG 图片 |
| 11 | `cleanup_scans` | 清理历史扫描 | keep_latest | 删除的扫描列表 |

### 5.2 核心工具工作流

**scan_disk：**
1. 查找 WizTree 可执行文件
2. 调用 WizTree CLI 执行扫描 → CSV 导出
3. csv_importer.py 流式导入 SQLite（边读 CSV 边写数据库，内存 < 50 MB）
4. 返回扫描摘要

**查询类工具（③-⑧）：** 全部走 SQL 查询，毫秒级返回

**compare_scans：** 用 FULL OUTER JOIN 对比两个 scan 的相同路径条目，计算 delta

---

## 六、数据流

### 6.1 扫描流程

```
用户 → scan_disk("C:")
  → 查找 WizTree 可执行文件
  → WizTree64.exe /export=xxx.csv（子进程执行，带超时）
  → csv_importer 流式读取 CSV，逐行写入 SQLite（内存 < 50 MB）
  → 返回扫描摘要
```

### 6.2 查询流程

```
用户 → top_entries(scan_id=1, kind="files", limit=20)
  → SELECT ... ORDER BY size DESC LIMIT 20
  → FastMCP 自动序列化为 JSON 返回
```

### 6.3 对比流程

```
用户 → compare_scans(scan_id_before=1, scan_id_after=2)
  → FULL OUTER JOIN 按路径匹配，计算 delta
  → 输出增长 Top N + 缩减 Top N
```

---

## 七、错误处理策略

| 场景 | 处理方式 |
|------|---------|
| WizTree 未找到 | 返回友好提示，列出已搜索的路径 |
| 扫描超时（默认 5 分钟） | 杀掉 WizTree 进程树，返回 ToolError |
| CSV 格式异常 | 跳过异常行，记录日志 |
| SQLite 写入失败 | 回滚事务，返回 ToolError |
| 查询的 scan_id 不存在 | 返回提示，建议用 list_scans 查看 |

---

## 八、与 disk_scan 项目的关系

wiztree-mcp 是**独立发布**的 MCP 服务器，不依赖 disk_scan 项目。

- **存储独立**：使用自己的 SQLite 数据库
- **数据共享**：可通过配置让 disk_scan 读取同一数据库
- **能力互补**：wiztree-mcp 做扫描和基础查询，disk_scan 做深度分析和交互式清理
- **无硬依赖**：两个项目可独立运行，也可协同工作

---

## 九、发布计划

### 9.1 发布渠道

1. **PyPI** — 主发布渠道，`pip install wiztree-mcp`
2. **MCP Registry** — 元数据注册，实现 `mcp install wiztree-mcp`
3. **GitHub** — 源码托管

### 9.2 版本策略

| 阶段 | 版本 | 功能 |
|------|------|------|
| MVP | 0.1.0 | 核心 11 个工具 + SQLite 存储 |
| 增强 | 0.2.0 | 进度通知、分页支持、资源模板 |
| 稳定 | 1.0.0 | 经过实际使用验证，API 稳定 |
| 扩展 | 1.1.0+ | Tasks 扩展、MCP Apps 可视化、远程 HTTP 传输 |

---

## 十、实施计划

### 阶段 1：基础设施
1. pyproject.toml — 项目配置
2. database.py — SQLite 建表、CRUD
3. models.py — 数据类
4. wiztree_cli.py — WizTree 查找与调用
5. csv_importer.py — CSV 流式导入

### 阶段 2：MCP 服务器
6. server.py — FastMCP 创建 + Lifespan
7. __init__.py + __main__.py — 包入口
8. tools/scan.py — scan_disk
9. tools/query.py — 查询类工具
10. tools/analysis.py — 分析类工具
11. tools/compare.py — compare_scans
12. tools/manage.py — 管理类工具

### 阶段 3：验证与发布
13. 测试 — 单元测试 + 集成测试
14. README.md — 文档
15. PyPI 发布
16. MCP Registry 注册

---

## 十一、与旧项目的关键区别

| 对比项 | 原项目 (TypeScript) | 新项目 (Python + SQLite) |
|--------|-------------------|------------------------|
| CSV 解析 | 每次全量 → 内存 1-2 GB | 一次性导入 → 内存 < 50 MB |
| 查询方式 | 遍历数组 O(n) | SQL 索引 O(log n) |
| 数据持久化 | 无（进程重启丢失） | SQLite 永久保存 |
| 跨 session 对比 | 两份 CSV 全量加载 | SQL JOIN，毫秒级 |
| 启动时间 | 秒级 | 毫秒级 |
| 依赖 | csv-parse + zod + sdk | 仅 mcp 一个依赖 |
| 发布 | npm | PyPI + MCP Registry |
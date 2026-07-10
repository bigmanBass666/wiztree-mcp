# MCP 构建研究：最佳实践与高级特性

## 研究日期
2026-07-10

## 概述

本文档基于 MCP (Model Context Protocol) 官方文档的深度精读，系统地整理了构建高质量 MCP 服务器的关键原则、最佳实践、高级特性、安全考虑和扩展机制。这些发现将直接指导我们 wiztree-mcp 项目的设计与实现。

---

## 一、架构核心概念

### 1.1 参与者模型

MCP 采用客户端-服务器架构，包含三个关键参与者：

| 参与者 | 角色 | 说明 |
|--------|------|------|
| **MCP Host** | AI 应用 | 协调和管理多个 MCP 客户端，如 Claude Desktop、VS Code |
| **MCP Client** | 连接组件 | 维护与单个 MCP 服务器的专用连接 |
| **MCP Server** | 上下文提供者 | 提供工具、资源和提示模板的程序 |

关键设计：MCP Host 为每个 MCP 服务器创建一个 MCP Client 对象。本地 STDIO 服务器通常服务单个客户端，远程 Streamable HTTP 服务器可服务多个客户端。

### 1.2 分层架构

MCP 包含两层：

- **数据层**：基于 JSON-RPC 2.0 的协议，定义消息结构和语义。涵盖生命周期管理、核心原语（工具、资源、提示）、通知和进度跟踪。
- **传输层**：定义通信机制和通道。支持 STDIO（本地进程间通信）和 Streamable HTTP（远程通信，支持 SSE 流式传输）。

### 1.3 生命周期管理

MCP 是一个有状态协议，通过初始化握手协商 capabilities：

1. 客户端发送 `initialize` 请求（含协议版本、capabilities、客户端信息）
2. 服务器响应自身 capabilities
3. 客户端发送 `notifications/initialized` 通知

关键点：capability negotiation 确保双方只使用都支持的功能。

### 1.4 核心原语

**服务器端原语：**

| 原语 | 控制者 | 说明 |
|------|--------|------|
| **Tools** | 模型 | LLM 主动调用的可执行函数 |
| **Resources** | 应用 | 只读数据源，提供上下文信息 |
| **Prompts** | 用户 | 预构建的交互模板 |

**客户端端原语：**

| 原语 | 说明 |
|------|------|
| **Sampling** | 服务器可通过客户端请求 LLM 补全 |
| **Elicitation** | 服务器可请求用户提供额外信息 |
| **Logging** | 服务器可向客户端发送日志消息 |
| **Roots** | 客户端指定文件系统边界 |

---

## 二、构建 MCP 服务器的关键实践

### 2.1 选择正确的 SDK

官方 SDK 分为三个层级（Tier）：

| 层级 | SDK | 说明 |
|------|-----|------|
| Tier 1 | TypeScript, Python, C#, Go | 功能最完整，官方维护承诺最高 |
| Tier 2 | Java, Rust | 功能完整，维护次之 |
| Tier 3 | Swift, Ruby, PHP, Kotlin | 社区驱动 |

**对于 Python 项目：** 使用 `mcp[cli]` 包（Python MCP SDK 1.2.0+）。推荐使用 FastMCP 类，它利用 Python 类型提示和文档字符串自动生成工具定义。

### 2.2 STDIO 服务器的日志规则

**最重要的规则：永远不要写 stdout。**

```python
# 错误（STDIO 下会破坏 JSON-RPC）
print("Processing request")

# 正确
print("Processing request", file=sys.stderr)

# 推荐
import logging
logging.info("Processing request")
```

HTTP 服务器则没有这个限制。

### 2.3 工具实现最佳实践

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
async def my_tool(param1: str, param2: int) -> str:
    """清晰的工具描述（会被用作工具说明）。

    Args:
        param1: 参数说明
        param2: 参数说明
    """
    # 实现逻辑
    return result
```

关键点：
- FastMCP 自动从类型提示和文档字符串生成 JSON Schema
- 工具名称要清晰（如 `calculator_arithmetic` 而非 `calculate`）
- 提供详尽的 `description` 字段
- 用 `inputSchema` 定义参数的类型和约束

### 2.4 资源实现要点

- 每个资源有唯一 URI（如 `file:///path/to/doc`）
- 声明 MIME 类型以支持适当的内容处理
- 支持两种发现模式：
  - **直接资源**：固定 URI，指向特定数据
  - **资源模板**：带参数的动态 URI（如 `weather://forecast/{city}/{date}`）
- 资源模板支持参数补全（如输入 "Par" 可建议 "Paris"）

### 2.5 提示模板

提示是用户控制的，需要显式调用。设计要点：

- 参数化，支持必选和可选参数
- 支持参数补全，帮助用户发现合法值
- 通常通过斜杠命令（`/plan-vacation`）或命令面板暴露

---

## 三、高级特性

### 3.1 资源订阅与实时通知

服务器可以在工具列表发生变化时发送 `notifications/tools/list_changed` 通知，客户端收到后重新获取工具列表。这需要服务器在初始化时声明 `"listChanged": true`。

通知类型：
- `notifications/tools/list_changed` — 工具列表变化
- `notifications/resources/list_changed` — 资源列表变化
- `notifications/prompts/list_changed` — 提示列表变化

### 3.2 进度通知

支持为长时间运行的操作发送进度更新。服务器可以发送进度通知，让客户端了解操作进度。

### 3.3 取消请求

客户端可以发送取消请求来中止正在进行的操作。服务器应当响应取消请求并释放相关资源。

### 3.4 分页

对于 `*/list` 方法，当返回结果较多时，支持使用游标进行分页：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [...],
    "nextCursor": "next-page-cursor"
  }
}
```

客户端在后续请求中包含 `cursor` 参数以获取下一页。

### 3.5 任务（Tasks）扩展 — 异步操作

MCP Tasks（实验性）允许服务器为长时间运行的操作返回持久化句柄，而非阻塞等待。

**任务生命周期状态：**

| 状态 | 含义 |
|------|------|
| `working` | 操作进行中 |
| `input_required` | 服务器需要客户端提供输入 |
| `completed` | 操作完成，包含最终结果 |
| `failed` | 操作失败，包含错误详情 |
| `cancelled` | 操作已被取消（合作式取消） |

**使用场景：**
- CI 流水线、批处理、模型训练等长耗时操作
- 人工审批等人在环工作流
- 包装外部作业系统（云部署、异步 API）
- 移动端和不可靠网络环境
- 批量处理（批量导入、大规模更新）

**实现要点：**
- 服务器必须在发送响应前持久化创建任务
- 客户端轮询时需遵守 `pollIntervalMs` 建议间隔
- 支持通过 `tasks/update` 提供中间输入
- 取消是合作式的 — 服务器可不执行

### 3.6 MCP Apps 扩展 — 交互式 UI

MCP Apps 允许服务器返回交互式 HTML 界面（数据可视化、表单、仪表板），直接在聊天中渲染。

**安全模型：**
- 在沙箱化 iframe 中运行
- 不能访问父页面 DOM、cookies 或 localStorage
- 所有通信通过 postMessage API 进行

**适用场景：**
- 复杂数据探索（交互式地图、图表）
- 多选项配置（部署设置表单）
- 富媒体查看（PDF、3D 模型、图片）
- 实时监控仪表板
- 多步骤工作流

---

## 四、错误处理与调试

### 4.1 服务器端错误处理

MCP 工具错误应该作为带 `isError: true` 的成功响应返回（非传输层失败）：

```python
@mcp.tool()
async def my_tool(input: str) -> str:
    try:
        result = await process(input)
        return result
    except ValueError as e:
        return f"Error: {str(e)}"
```

### 4.2 MCP Inspector

MCP Inspector 是主要的调试工具，可直接运行：

```bash
npx @modelcontextprotocol/inspector <command> <args>
```

功能：
- **Resources 标签**：列出资源、检查元数据、测试订阅
- **Prompts 标签**：显示提示模板、测试参数
- **Tools 标签**：列出工具、测试执行、查看结果
- **Notifications 面板**：查看服务器日志和通知

### 4.3 常见问题

| 问题类型 | 典型原因 | 解决方案 |
|---------|---------|---------|
| 路径问题 | 服务器可执行路径错误 | 使用绝对路径 |
| 配置错误 | JSON 语法错误、字段缺失 | 验证 JSON 格式 |
| 环境变量 | 缺少环境变量 | 在配置中指定 `env` |
| 工作目录 | 工作目录未定义 | 配置中使用绝对路径 |
| 连接失败 | 协议版本不兼容 | 检查 capability negotiation |

### 4.4 Claude Desktop 调试

**日志位置：**
- macOS: `~/Library/Logs/Claude`
- Windows: `%APPDATA%\Claude\logs`

**查看日志：**
```bash
# macOS
tail -n 20 -F ~/Library/Logs/Claude/mcp*.log

# Windows PowerShell
type "$env:AppData\Claude\logs\mcp*.log"
```

**启用 Chrome DevTools：**
创建 `developer_settings.json` 文件，内容为 `{"allowDevTools": true}`，放在：
- macOS: `~/Library/Application Support/Claude/`
- Windows: `$env:AppData\Claude\`

### 4.5 开发工作流

1. **初始开发**：使用 MCP Inspector 测试核心功能
2. **集成测试**：在目标 MCP 客户端中测试，监控日志
3. **快速迭代**：使用 MCP Inspector，修改代码后重新连接

**重启提示**：Claude Desktop 必须完全退出后重新启动（关闭窗口不够）。

---

## 五、安全最佳实践

### 5.1 攻击向量与防护

#### 混淆代理攻击

当 MCP 代理服务器使用静态 client_id 连接第三方 API 时，攻击者可利用 consent cookie 跳过授权确认。

**防护：** 每个 client_id 独立确认；确认页面显示客户端名称、请求的 scope、注册的 redirect_uri；使用 CSRF 保护和安全的 Cookie 属性。

#### Token Passthrough（禁止反模式）

MCP 服务器绝不能接受未明确为该服务器签发的 token。

#### SSRF 防护

- 生产环境强制 HTTPS
- 阻止私有 IP 范围
- 验证重定向目标
- 使用出口代理

#### 会话劫持防护

- 使用安全的随机会话 ID
- 会话 ID 绑定用户特定信息
- 会话不能替代认证

#### OAuth 授权 URL 验证

- 只允许 `http://` 和 `https://` 协议
- 避免 shell 命令打开 URL
- 实施 CSP 策略

### 5.2 本地服务器安全

- 执行前显示授权确认对话框
- 显示完整命令（含参数）
- 在沙箱中运行，使用最小权限
- STDIO 传输优先

### 5.3 Scope 最小化

- 渐进式最小权限 scope 模型
- 初始只授予低风险操作
- 避免通配符 scope

---

## 六、扩展机制

### 6.1 扩展概述

MCP 扩展是规范的可选补充，标识符格式：`{vendor-prefix}/{extension-name}`。

**关键规则：**
- 扩展默认禁用，需要显式 opt-in
- 在初始化握手的 `extensions` 字段中协商
- 一方不支持时，支持方需优雅降级

### 6.2 官方扩展

| 扩展 | 说明 |
|------|------|
| **MCP Apps** | 在对话中渲染交互式 UI |
| **MCP Tasks** | 异步任务执行 |
| **OAuth Client Credentials** | 机器对机器认证 |
| **Enterprise-Managed Authorization** | 企业集中授权 |

### 6.3 创建扩展

生命周期：提议 (SEP) -> 实现 -> 审核 -> 发布 -> 采用

要求：RFC 2119 语言、关联工作组、SDK 实现可选。

### 6.4 演进规则

- 与核心协议独立演进
- 优先使用 capability flags 而非创建新标识符
- 破坏性变更需使用新标识符

---

## 七、发布与注册

### 7.1 MCP Registry

MCP Registry 是官方中心化元数据仓库（预览阶段）。

**关键点：**
- 只存 `server.json` 元数据，不托管代码
- 服务器名：反向 DNS 格式（`io.github.username/server`）
- 通过 DNS 或 GitHub 认证验证命名空间
- 不支持私有服务器

**server.json 结构：**
```json
{
  "name": "io.github.my-username/weather",
  "version": "1.0.0",
  "packages": [{
    "registryType": "npm",
    "identifier": "@my-username/mcp-weather-server",
    "transport": { "type": "stdio" },
    "environmentVariables": [
      { "name": "API_KEY", "isRequired": true, "isSecret": true }
    ]
  }]
}
```

### 7.2 发布流程

1. 在 npm/PyPI 发布包
2. 在包中添加 `mcpName` 验证信息
3. 安装 `mcp-publisher` CLI
4. `mcp-publisher init` 生成 server.json
5. `mcp-publisher login github` 认证
6. `mcp-publisher publish` 发布

### 7.3 生态系统

MCP Registry -> 下游聚合器（市场/目录） -> MCP Host 应用

---

## 八、Python SDK 要点

### 8.1 安装

```bash
uv add "mcp[cli]" httpx
# 或
pip install "mcp[cli]" httpx
```

要求：Python 3.10+，MCP SDK 1.2.0+

### 8.2 FastMCP 类

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("server-name")

@mcp.tool()
async def my_tool(param: str) -> str:
    """工具描述"""
    return result

@mcp.resource("schema://database/tables")
async def get_schema() -> str:
    """获取数据库表结构"""
    return table_schema

@mcp.prompt()
async def my_prompt(topic: str) -> str:
    """提示模板"""
    return f"请帮我分析{topic}"

mcp.run(transport="stdio")
```

### 8.3 日志消息通知

```python
@server.tool()
async def my_tool(ctx: Context) -> str:
    await ctx.session.send_log_message(
        level="info", data="Server started successfully",
    )
    return "done"
```

支持 8 个 RFC 5424 日志级别（`debug` 到 `emergency`）。

---

## 九、客户端最佳实践（对服务器设计的启示）

### 9.1 渐进式发现

当工具数量多时，采用三层搜索模式：
1. **Catalog**：`search_tools` 元工具返回匹配的工具名和描述
2. **Inspect**：获取单个工具的完整定义
3. **Execute**：调用工具

**对服务器的启示：** 工具名和描述要清晰；支持 `listChanged` 通知。

### 9.2 程序化工具调用

模型编写代码在沙箱中批量调用工具，只有最终结果返回上下文。

**对服务器的启示：** 提供 `outputSchema`；设计可组合的接口。

### 9.3 动态服务器管理

Host 按需连接/断开服务器。

**对服务器的启示：** 服务器轻量、专注；初始化快；capability 声明清晰。

### 9.4 缓存与刷新

- 客户端应缓存工具定义（避免重复 `tools/list` 往返）
- 收到 `list_changed` 通知时重新索引搜索目录
- 工具按源服务器分组展示
- 注意提示缓存边界：追加定义而非重排序 tools 数组

---

## 十、设计哲学

MCP 的 7 项设计原则及对我们的启示：

| 原则 | 含义 | 对我们的启示 |
|------|------|-------------|
| **收敛而非选择** | 一个问题一个解法 | 避免设计重叠功能 |
| **可组合而非特定** | 用基础原语构建 | 提供基础构建块而非封装 |
| **互操作优于优化** | 支持不同能力级别 | 提供友好的降级行为 |
| **稳定优于速度** | 添加容易，移除难 | 工具接口设计需谨慎 |
| **能力优于补偿** | 不为临时限制加永久结构 | 避免假设模型行为模式 |
| **演示优于推演** | 实现优于理论 | 构建原型验证设计 |
| **实用优于纯粹** | 好的实际权衡 | 不要过度追求理论优雅 |

---

## 十一、对我们项目的启示

### 11.1 技术选型
- Python + FastMCP（uv 管理依赖）
- STDIO 传输层（本地 WizTree 交互）
- 日志全部写入 stderr

### 11.2 工具设计
- 每个工具关注单一功能：扫描、查询、分析、比较
- 工具名清晰描述功能（如 `scan_directory`、`search_files`）
- 提供详尽的参数描述和类型约束

### 11.3 资源设计
- 扫描结果可作为资源暴露（如 `wiztree://scan/{id}/summary`）
- 资源模板支持查询特定目录/文件类型

### 11.4 错误处理
- 所有工具返回友好的错误消息
- 使用 `isError` 机制而非抛出异常
- 利用 MCP Inspector 进行开发调试

### 11.5 安全考虑
- STDIO 传输自然限制访问范围
- 工具涉及文件操作时遵循最小权限原则
- 考虑发布到 MCP Registry（PyPI 托管包，Registry 托管元数据）

### 11.6 值得追求的高级特性
- 支持 `listChanged` 通知以支持动态更新
- 为长时间运行的扫描操作考虑 Tasks 扩展
- 为 Treemap 可视化考虑 MCP Apps 扩展
- 实现资源模板以支持灵活的查询
- 为大量结果实现分页支持

---

## 十二、参考链接

| 类别 | 链接 |
|------|------|
| 架构 | https://modelcontextprotocol.io/docs/learn/architecture |
| 服务器概念 | https://modelcontextprotocol.io/docs/learn/server-concepts |
| 客户端概念 | https://modelcontextprotocol.io/docs/learn/client-concepts |
| 版本控制 | https://modelcontextprotocol.io/docs/learn/versioning |
| 构建服务器 | https://modelcontextprotocol.io/docs/develop/build-server |
| 客户端最佳实践 | https://modelcontextprotocol.io/docs/develop/clients/client-best-practices |
| 远程服务器 | https://modelcontextprotocol.io/docs/develop/connect-remote-servers |
| 调试指南 | https://modelcontextprotocol.io/docs/tools/debugging |
| MCP Inspector | https://modelcontextprotocol.io/docs/tools/inspector |
| 安全最佳实践 | https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices |
| 扩展概述 | https://modelcontextprotocol.io/extensions/overview |
| Tasks 扩展 | https://modelcontextprotocol.io/extensions/tasks/overview |
| Apps 扩展 | https://modelcontextprotocol.io/extensions/apps/overview |
| Auth 扩展 | https://modelcontextprotocol.io/extensions/auth/overview |
| Registry | https://modelcontextprotocol.io/registry/about |
| Registry 快速入门 | https://modelcontextprotocol.io/registry/quickstart |
| SDK | https://modelcontextprotocol.io/docs/sdk |
| 设计原则 | https://modelcontextprotocol.io/community/design-principles |
# MCP 官方文档全量精读报告

## 研究日期
2026-07-10

---

## 一、入门与概念

### 1.1 什么是 MCP

- **核心定义**：MCP (Model Context Protocol) 是一个开源标准，用于连接 AI 应用程序与外部系统。可以将其视为 AI 应用的 "USB-C 接口"。
- **能做什么**：AI 应用可以通过 MCP 连接数据源（本地文件、数据库）、工具（搜索引擎、计算器）和工作流（专用提示词）。
- **为何重要**：
  - 对开发者：减少集成 AI 应用时的开发时间和复杂度
  - 对 AI 应用：提供一个完整的数据源、工具和应用生态系统
  - 对最终用户：获得更强大的 AI 应用，能访问数据并代表用户执行操作
- **生态支持**：Claude、ChatGPT、VS Code、Cursor、MCPJam 等都支持 MCP。

### 1.2 架构概览

MCP 采用 **客户端-服务器架构 (client-server)**，包含三个关键参与者：

- **MCP Host（主机）**：协调一个或多个 MCP 客户端的 AI 应用程序
- **MCP Client（客户端）**：维持与 MCP 服务器的连接，为主机提供上下文
- **MCP Server（服务器）**：向客户端提供上下文和能力的程序

**关键架构特点**：
- 每个主机可以创建多个客户端实例，每个客户端与一个服务器维持 1:1 的独立连接
- 本地 MCP 服务器（使用 STDIO 传输）通常服务单个客户端
- 远程 MCP 服务器（使用 Streamable HTTP）通常服务多个客户端

**两层架构**：
- **数据层 (Data Layer)**：基于 JSON-RPC 2.0 的协议，包括生命周期管理、核心原语（工具、资源、提示）、通知
- **传输层 (Transport Layer)**：定义通信机制，支持 STDIO 和 Streamable HTTP 两种传输

### 1.3 服务器核心原语

| 原语 | 控制方 | 说明 | 协议方法 |
|------|--------|------|---------|
| **Tools（工具）** | 模型控制 | LLM 可主动调用的函数，可写数据库、调外部 API、修改文件 | `tools/list`, `tools/call` |
| **Resources（资源）** | 应用控制 | 提供只读信息的数据源，用于提供上下文 | `resources/list`, `resources/read`, `resources/subscribe`, `resources/templates/list` |
| **Prompts（提示）** | 用户控制 | 预建的指令模板，告诉模型如何使用特定工具和资源 | `prompts/list`, `prompts/get` |

### 1.4 客户端核心能力

| 能力 | 说明 | 用途 |
|------|------|------|
| **Elicitation（引述）** | 服务器可通过客户端向用户请求信息 | 收集用户输入、确认操作 |
| **Roots（根目录）** | 客户端指定文件系统边界 | 通知服务器可操作的目录范围 |
| **Sampling（采样）** | 服务器通过客户端请求 LLM 补全 | 实现代理行为，无需服务器直接对接 LLM |

### 1.5 版本管理

- 版本格式：`YYYY-MM-DD`（基于日期），指示最后一次向后不兼容变更的日期
- 向后兼容的更新不会增加版本号
- 当前版本：**2025-11-25**
- 版本协商在初始化阶段完成：客户端发送支持的版本，服务器回应，如果不兼容则断开连接

---

## 二、规范细节（2025-11-25）

### 2.1 基础协议

#### JSON-RPC 消息格式

所有 MCP 消息必须遵循 JSON-RPC 2.0 规范，定义三种消息类型：

1. **Requests（请求）**：必须包含 `id`（string 或 integer，不能为 null），`method`，可选 `params`
   - 与标准 JSON-RPC 不同：ID 不能为 null，ID 在同一会话内不能重复使用
2. **Responses（响应）**：包含与请求相同的 ID
   - **Result Response**：成功时返回 `result` 字段
   - **Error Response**：失败时返回 `error` 字段（含 `code`, `message`, 可选 `data`）
3. **Notifications（通知）**：没有 ID（单向消息），接收方不能发送响应

#### 关键规范约束

- 请求 ID 在同一会话中**不能重复使用**
- JSON-RPC 通知的 ID 必须省略
- 所有消息用 **UTF-8 编码**

### 2.2 生命周期管理

MCP 是一个**有状态协议**，定义三个生命周期阶段：

#### 阶段 1：初始化
- 客户端发送 `initialize` 请求，包含协议版本、客户端能力和实现信息
- 服务器回应包含协议版本、服务器能力和实现信息
- 客户端发送 `notifications/initialized` 通知表示准备就绪
- 在初始化完成前，双方只能发送 `ping` 请求（客户端）或 `ping` 和 `logging` 请求（服务器）

#### 阶段 2：操作
- 按协商的能力交换消息
- 双方必须遵循协商的协议版本，只使用成功协商的能力

#### 阶段 3：关闭
- STDIO：关闭子进程的输入流，等待退出，必要时发送 SIGTERM/SIGKILL
- HTTP：关闭关联的 HTTP 连接
- 没有特定的关闭消息——通过底层传输机制通知连接终止

#### 超时与错误处理

- 所有请求应设置超时，超时后发送取消通知
- 收到进度通知时可重置超时时钟，但仍有最大超时限制
- 常见错误：协议版本不匹配、能力协商失败、请求超时

### 2.3 传输协议

#### STDIO 传输（本地服务器）
- 客户端将服务器作为子进程启动
- 服务器从 `stdin` 读取 JSON-RPC 消息，向 `stdout` 写入消息
- 消息以换行符分隔，不能包含嵌入的换行符
- 服务器可以向 `stderr` 写入日志（客户端可捕获、转发或忽略）
- 双方都不能写入非 MCP 消息的内容到 `stdin/stdout`

#### Streamable HTTP 传输（远程服务器）
- **替代了 2024-11-05 的 HTTP+SSE 传输**
- 服务器提供单个 MCP 端点，支持 POST 和 GET
- **POST 请求**：发送 JSON-RPC 消息到服务器
  - 如果是通知/响应，服务器返回 202 Accepted（无 body）
  - 如果是请求，服务器要么返回 `text/event-stream`（SSE 流），要么返回 `application/json`
- **GET 请求**：打开 SSE 流，监听服务器消息
- **会话管理**：服务器可在初始化时通过 `MCP-Session-Id` 头分配会话 ID
  - 会话 ID 应全局唯一且加密安全（如 UUID、JWT）
  - 客户端在所有后续请求中包含 `MCP-Session-Id`
  - 可恢复/重新投递 (resumability)：SSE 事件可带 `id` 字段，客户端可用 `Last-Event-ID` 重连
- **安全性**：服务器必须验证 `Origin` 头防止 DNS rebinding 攻击；本地运行时应只绑定到 localhost
- **协议版本头**：客户端必须在所有 HTTP 请求中包含 `MCP-Protocol-Version` 头

### 2.4 授权 (Authorization)

基于 **OAuth 2.1**（IETF DRAFT），可选实现。

**核心要求**：
- HTTP 传输的服务器应遵循此规范
- STDIO 传输不应遵循，应从环境获取凭据
- 授权服务器必须实现 OAuth 2.1 安全措施
- 客户端和支持的授权服务器应支持 OAuth Client ID Metadata Documents

**授权流程**：
1. 客户端发送未经认证的请求，服务器返回 401（含 `WWW-Authenticate` 头）
2. 客户端从头部提取资源元数据 URL
3. 发现授权服务器（尝试 OAuth 2.0 和 OpenID Connect 发现端点）
4. 客户端注册（Client ID Metadata Documents / 预注册 / 动态注册）
5. 授权码流程（含 PKCE）
6. 获取访问令牌，用于后续请求

**关键安全要求**：
- 必须使用 `resource` 参数（RFC 8707）限定令牌的目标资源
- 必须实现 PKCE（S256 方法）
- 所有授权服务器端点必须使用 HTTPS
- 必须验证令牌的 audience
- **禁止令牌穿透 (Token Passthrough)**

### 2.5 工具规范 (Tools)

工具是 **模型控制** 的原语。

#### 工具定义关键字段：
- `name`: 唯一标识符，1-128 字符，仅允许字母、数字、下划线、连字符、点
- `inputSchema`: JSON Schema（默认为 2020-12），不能为 null
- `outputSchema`: 可选，定义输出结构
- `annotations`: 可选，描述工具行为（客户端应将注解视为不可信的）
- `execution.taskSupport`: `forbidden`（默认）、`optional`、`required`

#### 工具执行
- 客户端发送 `tools/call` 请求（含 `name` 和 `arguments`）
- 响应包含 `content` 数组和多类型内容（text、image、audio、resource_link、embedded resource）
- 也支持 `structuredContent` 字段输出结构化 JSON

#### 错误处理
- **协议错误**：标准 JSON-RPC 错误（未知工具、格式错误等）
- **工具执行错误**：在结果中设置 `isError: true`，LLM 可用来自我修正

#### 安全要求
- 必须有 **人类在回路中 (human in the loop)**，能拒绝工具调用
- 客户端应在敏感操作前提示用户确认
- 应在调用前向用户展示工具输入

### 2.6 资源规范 (Resources)

资源是 **应用控制** 的原语。

- 每个资源有唯一 **URI**（RFC 3986）
- 支持标准 URI scheme：`file://`、`https://`、`git://`、自定义 scheme
- 资源可以是文本或二进制（blob）内容
- 支持资源模板（带 URI 模板参数）
- 可选订阅机制：客户端可以订阅资源变更通知

#### 资源注解 (Annotations)
- `audience`: 目标受众（`["user"]`, `["assistant"]`, 或两者）
- `priority`: 0.0 到 1.0 的重要性值
- `lastModified`: ISO 8601 时间戳

#### 错误码
- 资源未找到：`-32002`
- 内部错误：`-32603`

### 2.7 提示规范 (Prompts)

提示是 **用户控制** 的原语，需要用户显式调用。

**消息内容类型**：
- `text`: 纯文本
- `image`: base64 编码图片 + MIME type
- `audio`: base64 编码音频 + MIME type
- `resource`: 嵌入式资源引用（含 URI、MIME type、文本或 blob 数据）

### 2.8 分页 (Pagination)

- 使用**不透明游标 (opaque cursor)** 方式
- 服务器决定页面大小，客户端不能假定固定大小
- 客户不能解析或修改游标
- 游标不跨会话持久化

### 2.9 日志 (Logging)

- 遵循 **RFC 5424** syslog 严重级别（debug -> emergency 共 8 级）
- 客户端可设置最低日志级别（`logging/setLevel`）
- 服务器通过 `notifications/message` 发送日志
- 日志不能包含凭据、个人识别信息或内部系统细节

### 2.10 自动补全 (Completion)

- 服务器可提供提示参数和资源 URI 参数的自动补全建议
- 两种引用类型：`ref/prompt`（按名称）和 `ref/resource`（按 URI）
- 最多返回 100 条建议

### 2.11 取消 (Cancellation)

- 通过 `notifications/cancelled` 通知取消进行中的请求
- 包含被取消请求的 ID 和可选原因字符串
- **初始化请求不能被取消**
- 任务增强请求使用 `tasks/cancel` 代替取消通知

### 2.12 Ping

- 简单的请求/响应模式：`ping` -> 空响应 `{}`
- 任一方可发起

### 2.13 进度追踪 (Progress)

- 请求方在 `_meta.progressToken` 中传入进度令牌
- 执行方发送 `notifications/progress` 通知
- progress 值必须递增
- 对于任务增强请求，progressToken 在整个任务生命周期内有效

### 2.14 任务 (Tasks) **实验性**

任务是在 2025-11-25 引入的**实验性**特性。

**核心概念**：
- 任务是对请求的持久化包装，支持轮询、延迟结果检索
- 适合：耗时计算、批处理、外部 job API 集成
- 任务有唯一 `taskId`（由接收方生成）
- 任务状态机：`working` -> `input_required` / `completed` / `failed` / `cancelled`

**任务生命周期**：
1. **创建**：请求中包含 `task` 字段（含可选的 `ttl`），接收方返回 `CreateTaskResult`
2. **轮询**：请求方通过 `tasks/get` 轮询状态
3. **获取结果**：完成后通过 `tasks/result` 获取最终结果
4. **取消**：通过 `tasks/cancel` 取消

**工具级任务协商**：
- 工具的 `execution.taskSupport` 声明是否支持任务
- `forbidden`（默认）/ `optional` / `required`

### 2.15 客户端 Roots

- 客户端指定文件系统边界：`file://` URI + 可选名称
- 服务器可请求根列表（`roots/list`）和接收变更通知
- **注意**：Roots 是协调机制，不是安全边界

### 2.16 客户端 Sampling

- 服务器通过客户端请求 LLM 补全，无需直接调用 LLM API
- 支持多轮工具调用（multi-turn tool loop）
- **Human-in-the-loop 设计**：用户可审查和修改请求和响应
- 模型选择：使用 `modelPreferences`（hints + 优先级向量）

### 2.17 引述 (Elicitation)

- 服务器可通过客户端向用户请求信息
- **Form 模式**：结构化表单，Schema 限于扁平对象和基本类型，不能请求敏感信息
- **URL 模式**：用户跳转到外部 URL，适合敏感/认证操作
- 三种响应动作：`accept`、`decline`、`cancel`

---

## 三、构建与开发

### 3.1 构建 MCP 服务器

- Python 使用 `mcp` 包 + `FastMCP` 快速定义工具
- 支持 STDIO 和 SSE 传输
- `@server.tool()`、`@server.resource()`、`@server.prompt()` 装饰器

### 3.2 构建 MCP 客户端

- Python 使用 `mcp` 包的 `ClientSession` + `StdioClient`/`StreamableHttpClient`
- 标准流程：创建传输 -> 创建会话 -> `session.initialize()`
- 工具发现和调用：`list_tools()` 和 `call_tool()`

### 3.3 客户端最佳实践

**两大模式**：

1. **渐进式工具发现** — 解决数百个工具定义塞满上下文窗口
   - 提供 `search_tools` 元工具
   - 三层：目录->检查->执行
   - 工具定义占上下文 1%-5% 时切换

2. **编程式工具调用/代码模式** — 解决中间结果流过模型
   - 模型在沙箱中写代码调用工具
   - 仅最终结果返回模型
   - 需沙箱环境（Deno、Monty、Wasmtime 等）

**动态服务器管理**：仅在需要时连接服务器

### 3.4 本地 vs 远程连接

- **本地**：Claude Desktop 的 `claude_desktop_config.json` 配置
- **远程**：通过 Custom Connectors 在 Claude.ai 配置

### 3.5 Agent Skills

- `mcp-server-dev` 插件：build-mcp-server / build-mcp-app / build-mcpb
- 四种部署：Remote HTTP / MCP Apps / MCP Bundles / Local STDIO

---

## 四、工具与调试

### 4.1 调试三层工具

1. **MCP Inspector** — 交互式测试 UI
2. **服务器日志** — stderr（STDIO）或 log message notifications
3. **客户端开发者工具** — 各客户端日志和连接状态

### 4.2 MCP Inspector

- `npx @modelcontextprotocol/inspector <server command>`
- 支持 Resources、Prompts、Tools 标签和 Notifications 面板

### 4.3 SDK

- Tier 1（全功能）：TypeScript、Python、C#、Go
- Tier 2：Java、Rust
- Tier 3：Swift、Ruby、PHP、Kotlin

---

## 五、扩展机制

### 5.1 扩展总览

- 标识符：`{vendor-prefix}/{extension-name}`
- 官方扩展：OAuth Client Credentials、Enterprise-Managed Auth、MCP Apps、MCP Tasks
- 始终默认禁用，需要显式选入
- 降级到核心协议行为

### 5.2 Tasks 扩展

- 通过 `io.modelcontextprotocol/tasks` 标识
- 比内置 Tasks 更灵活：`tasks/update` 支持中途输入

---

## 六、安全

### 6.1 攻击向量及缓解

1. **混淆代理 (Confused Deputy)** — 必须实现每次客户端独立同意
2. **令牌穿透 (Token Passthrough)** — 明确禁止
3. **SSRF** — 强制 HTTPS、拦截私有 IP、验证重定向
4. **会话劫持** — 非确定性会话 ID、绑定用户身份
5. **本地服务器攻陷** — 显示完整命令、沙箱执行
6. **OAuth URL 验证** — 只允许 http/https scheme
7. **作用域最小化** — 逐步提升权限

### 6.2 授权教程

- 授权可选但强烈推荐
- STDIO 使用环境凭据
- HTTP 使用 OAuth 2.1

---

## 七、Registry 发布

### 7.1 Registry 概述

- 官方集中元数据仓库（预览阶段）
- 存储 `server.json` 格式元数据
- 反向 DNS 命名：`io.github.user/server-name`
- 不支持私有服务器
- 下游聚合器消费 Registry API

### 7.2 发布步骤

1. 添加 `mcpName` 到 `package.json`
2. 发布包到 npm
3. 安装 `mcp-publisher` CLI
4. 创建 `server.json`
5. 认证：`mcp-publisher login github`
6. 发布：`mcp-publisher publish`

---

## 八、设计原则

1. **趋同而非选择** — 一个问题一种解法
2. **组合而非特化** — 基本原语构建所有用例
3. **互操作而非优化** — 在不同能力级别间优雅降级
4. **稳定而非速度** — 以十年为周期优化
5. **能力而非补偿** — 不为模型限制加永久结构
6. **演示而非空谈** — 工作实现优于理论
7. **实用而非纯粹** — 实际可用性优先
8. **标准化而非创新** — 标准化已证明的模式

---

## 九、综合启示

### 对服务器开发者
- 理解三个原语的不同控制模型
- 传输选择：STDIO（本地）vs Streamable HTTP（远程）
- 工具设计：清晰的 description、完整的 inputSchema、可选 outputSchema
- 安全：人类批准、不请求密码、验证 token audience

### 对客户端开发者
- 完整生命周期管理：初始化协商版本和能力
- 支持两种传输或至少一种
- Human-in-the-loop：采样和工具审批
- 渐进式发现和编程式调用最佳实践
- 考虑 Tasks 扩展

---

## 十、参考链接

### 入门与概念
- https://modelcontextprotocol.io/docs/getting-started/intro.md
- https://modelcontextprotocol.io/docs/learn/architecture.md
- https://modelcontextprotocol.io/docs/learn/server-concepts.md
- https://modelcontextprotocol.io/docs/learn/client-concepts.md
- https://modelcontextprotocol.io/docs/learn/versioning.md

### 核心规范
- https://modelcontextprotocol.io/specification/2025-11-25/index.md
- https://modelcontextprotocol.io/specification/2025-11-25/basic/index.md
- https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle.md
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports.md
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization.md
- https://modelcontextprotocol.io/specification/2025-11-25/server/tools.md
- https://modelcontextprotocol.io/specification/2025-11-25/server/resources.md
- https://modelcontextprotocol.io/specification/2025-11-25/server/prompts.md

### 客户端规范
- https://modelcontextprotocol.io/specification/2025-11-25/client/roots.md
- https://modelcontextprotocol.io/specification/2025-11-25/client/sampling.md
- https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation.md

### 工具与开发
- https://modelcontextprotocol.io/docs/develop/build-server.md
- https://modelcontextprotocol.io/docs/develop/build-client.md
- https://modelcontextprotocol.io/docs/develop/clients/client-best-practices.md
- https://modelcontextprotocol.io/docs/tools/debugging.md
- https://modelcontextprotocol.io/docs/tools/inspector.md
- https://modelcontextprotocol.io/docs/sdk.md

### 扩展与安全
- https://modelcontextprotocol.io/extensions/overview.md
- https://modelcontextprotocol.io/extensions/tasks/overview.md
- https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices.md
- https://modelcontextprotocol.io/docs/tutorials/security/authorization.md

### Registry 与设计原则
- https://modelcontextprotocol.io/registry/about.md
- https://modelcontextprotocol.io/registry/quickstart.md
- https://modelcontextprotocol.io/community/design-principles.md

### llms.txt
- https://modelcontextprotocol.io/llms.txt
# CLI Agent

> **Language / 语言**: [English](#cli-agent-english) | [中文](#cli-agent-中文)

---

<a id="cli-agent-english"></a>

A CLI agent built from scratch in Python, implementing the ReAct (Reasoning + Acting) pattern. An interactive coding assistant that reads files, edits code, manages directories, and safely handles destructive operations—all from the terminal with streaming output.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended)
- An OpenAI API key **or** a ByteDance GPT API key (`GPT_AK`)

## Setup

1. Clone the repo and install dependencies:

```bash
uv sync
```

2. Create a `.env` file in the project root. **Either** OpenAI **or** ByteDance GPT:

**Option A — OpenAI:**
```
OPENAI_API_KEY=your-api-key-here
```

**Option B — ByteDance GPT** (uses Azure-compatible API):
```
GPT_AK=your-bytedance-api-key
```

Optional env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_BYTEDANCE` | auto | `true` = ByteDance, `false` = OpenAI. Unset = auto-detect from keys |
| `OPENAI_MODEL` | `gpt-4o-mini` (OpenAI) / `gpt-5.2-2025-12-11` (ByteDance) | Model to use |
| `OPENAI_MAX_TOKENS` | `4096` | Max completion tokens |
| `GPT_ENDPOINT` | `https://search.bytedance.net/gpt/openapi/online/v2/crawl` | ByteDance API base URL; include `/crawl` if you get 404 |
| `GPT_MODEL` | — | Overrides model when using ByteDance |
| `LOG_DEBUG` | `false` | `true` = stream model response tokens to logs (requires log-server + `LOG_LEVEL=DEBUG`) |
| `LOG_LEVEL` | `DEBUG` | Log level: DEBUG, INFO, WARNING, ERROR |
| `LOG_SERVER_PORT` | `9999` | Port for log-server (agent and log-server must use the same value) |

## Running

```bash
uv run agent
```

For live debug logging, start the log server in a separate terminal before launching the agent:

```bash
uv run log-server
```

Type your message and press Enter. Use `quit`, `exit`, or Ctrl+C to leave.

---

## Features

### Streaming ReAct Loop

The agent uses the ReAct pattern — it reasons, calls tools, observes results, and repeats until the task is complete. All output streams in real time: text tokens, tool invocations, and tool results appear as they arrive.

**Turn flow:**
1. User sends a message
2. Model generates reasoning and/or tool calls
3. Agent executes tools, appends results to conversation
4. Model continues until it produces a final text response
5. Multi-turn context is preserved across the entire session

### Tools

| Tool | Category | Description |
|------|----------|-------------|
| `read_file` | Read | Read the full contents of a file |
| `list_dir` | Read | List files and directories at a path |
| `write_file` | Write | Create or fully overwrite a file |
| `str_replace` | Write | Replace a unique string within a file (targeted edit) |
| `file_rewrite` | Write | Overwrite an entire file with new content |
| `make_dir` | Write | Create a directory (with parent dirs if needed) |
| `delete_file` | Delete | Delete a file (requires confirmation or prior permission grant) |
| `delete_dir` | Delete | Recursively delete a directory (requires confirmation or prior permission grant) |
| `check_permissions` | Utility | Query which paths have delete permission granted |
| `echo` | Utility | Echo a message (for testing) |

### Permission System for Destructive Operations

Delete operations (`delete_file`, `delete_dir`) are protected by a session-scoped permission gate:

1. **First deletion attempt** on a path opens an interactive confirmation panel
2. User chooses from three options:
   - **Grant permission** — approve this path and all children for the rest of the session (no further prompts)
   - **Delete once** — approve this single deletion only
   - **Cancel** — abort the operation
3. Granted permissions persist in memory for the session; parent-path grants cover all children

### Safety Features

- **Path validation**: All write and edit operations are confined to the current working directory. Paths with `..` that escape the workspace are rejected.
- **Atomic writes**: File writes go to a temp file first, then atomically renamed — no partial writes on failure.
- **Syntax checking**: After editing Python or JSON files, the agent validates syntax and surfaces warnings.
- **Non-TTY safe**: Delete confirmation defaults to "cancel" when stdin is not a terminal (e.g., in scripts or CI).

### Rich Terminal UI

- Startup banner with project name and version
- Color-coded output: user prompts in green, tool calls with `⟳ tool_name(args)`, errors in red
- Delete confirmation rendered as a highlighted panel with numbered options
- Live log server for debug output without polluting the agent REPL

---

## Project Structure

```
src/agent/
├── cli/
│   ├── app.py            # Main entry point — REPL loop, startup
│   └── display.py        # Rich UI: banner, prompts, streaming, delete confirm
├── config/
│   ├── settings.py       # Settings dataclass, .env loading, validation
│   └── context.py        # CLAUDE.md-style context loading (planned)
├── core/
│   ├── loop.py           # ReAct agent loop (streaming + non-streaming)
│   ├── state.py          # Conversation state — message history management
│   └── compaction.py     # Context compaction (planned)
├── permissions/
│   └── gates.py          # Session-scoped delete permission tracking
├── tools/
│   ├── registry.py       # Tool definitions (OpenAI format) + dispatch
│   ├── edit_common.py    # Shared: path validation, atomic writes, syntax checks
│   ├── delete_common.py  # Shared: confirmation dialog + delete execution
│   ├── read_file.py      # read_file tool
│   ├── list_dir.py       # list_dir tool
│   ├── write_file.py     # write_file tool
│   ├── str_replace.py    # str_replace tool
│   ├── file_rewrite.py   # file_rewrite tool
│   ├── make_dir.py       # make_dir tool
│   ├── delete_file.py    # delete_file tool
│   ├── delete_dir.py     # delete_dir tool
│   ├── check_permissions.py  # check_permissions tool
│   └── dummy.py          # echo tool
├── logger.py             # Socket-based logger (sends to log server)
└── log_server.py         # TCP log server for live debug output
```

## Architecture

The agent is built in three layers:

**CLI layer** (`cli/`) — REPL entry point. Collects user input, drives the streaming loop, renders output via Rich.

**Core layer** (`core/`) — Stateful ReAct loop. Manages conversation history in `ConversationState`, calls the OpenAI API with tool definitions, and routes tool calls back through the tool registry until the model signals it is done.

**Tools layer** (`tools/`) — Self-contained tool implementations. Each tool returns a plain string (success message or error). The registry maps tool names to callables and wraps execution in exception handlers so errors never crash the loop.

The **permissions layer** (`permissions/`) sits between the core loop and the delete tools, maintaining a session-level set of granted paths checked before any destructive operation.

## Testing

```bash
uv run pytest
```

Tests live in `tests/`. The delete permission system has the most comprehensive coverage (`tests/test_delete_permissions.py`).

## License

MIT

---

<a id="cli-agent-中文"></a>

# CLI Agent 中文

> **Language / 语言**: [English](#cli-agent-english) | [中文](#cli-agent-中文)

一个从零开始用 Python 构建的命令行智能体，实现了 ReAct（推理 + 行动）模式。这是一个交互式编程助手，可以读取文件、编辑代码、管理目录，并安全处理危险操作——全部在终端中以流式输出的方式进行。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐）
- OpenAI API 密钥

## 安装配置

1. 克隆仓库并安装依赖：

```bash
uv sync
```

2. 在项目根目录创建 `.env` 文件：

```
OPENAI_API_KEY=your-api-key-here
```

可选环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_MODEL` | `gpt-4o-mini` | 使用的模型 |
| `OPENAI_MAX_TOKENS` | `4096` | 最大补全 token 数 |

## 运行

```bash
uv run agent
```

如需实时调试日志，在启动 agent 前在另一个终端启动日志服务器：

```bash
uv run log-server
```

输入消息后按 Enter 发送。使用 `quit`、`exit` 或 Ctrl+C 退出。

---

## 功能特性

### 流式 ReAct 循环

Agent 使用 ReAct 模式——推理、调用工具、观察结果，循环执行直到任务完成。所有输出实时流式传输：文本 token、工具调用和工具结果在到达时立即显示。

**对话流程：**
1. 用户发送消息
2. 模型生成推理和/或工具调用
3. Agent 执行工具，将结果追加到对话中
4. 模型持续运行，直到生成最终文本回复
5. 整个会话期间保留多轮上下文

### 工具列表

| 工具 | 类别 | 说明 |
|------|------|------|
| `read_file` | 读取 | 读取文件的完整内容 |
| `list_dir` | 读取 | 列出指定路径下的文件和目录 |
| `write_file` | 写入 | 创建或完整覆写文件 |
| `str_replace` | 写入 | 替换文件中的特定字符串（精准编辑） |
| `file_rewrite` | 写入 | 用新内容覆写整个文件 |
| `make_dir` | 写入 | 创建目录（如需要会自动创建父目录） |
| `delete_file` | 删除 | 删除文件（需要确认或预先授权） |
| `delete_dir` | 删除 | 递归删除目录（需要确认或预先授权） |
| `check_permissions` | 工具 | 查询哪些路径已被授予删除权限 |
| `echo` | 工具 | 回显消息（用于测试） |

### 危险操作权限系统

删除操作（`delete_file`、`delete_dir`）受会话级权限门控保护：

1. **首次删除**某路径时，会打开交互式确认面板
2. 用户可从三个选项中选择：
   - **授予权限** — 批准该路径及其所有子路径在本次会话中的删除权限（后续不再提示）
   - **仅此一次** — 仅批准本次删除操作
   - **取消** — 中止操作
3. 授予的权限在会话期间保留于内存中；对父路径的授权覆盖所有子路径

### 安全特性

- **路径校验**：所有写入和编辑操作限制在当前工作目录内。包含 `..` 且试图逃出工作区的路径会被拒绝。
- **原子写入**：文件写入先写入临时文件，再原子性重命名——失败时不会产生残缺文件。
- **语法检查**：编辑 Python 或 JSON 文件后，agent 会验证语法并显示警告。
- **非 TTY 安全**：当 stdin 不是终端时（如在脚本或 CI 中），删除确认默认为"取消"。

### 丰富的终端 UI

- 带有项目名称和版本的启动横幅
- 颜色编码输出：用户提示为绿色，工具调用显示为 `⟳ tool_name(args)`，错误显示为红色
- 删除确认以带编号选项的高亮面板呈现
- 实时日志服务器，调试输出不污染 agent REPL

---

## 项目结构

```
src/agent/
├── cli/
│   ├── app.py            # 主入口 — REPL 循环、启动
│   └── display.py        # Rich UI：横幅、提示、流式输出、删除确认
├── config/
│   ├── settings.py       # 配置数据类，.env 加载与校验
│   └── context.py        # CLAUDE.md 风格的上下文加载（规划中）
├── core/
│   ├── loop.py           # ReAct agent 循环（流式与非流式）
│   ├── state.py          # 对话状态 — 消息历史管理
│   └── compaction.py     # 上下文压缩（规划中）
├── permissions/
│   └── gates.py          # 会话级删除权限追踪
├── tools/
│   ├── registry.py       # 工具定义（OpenAI 格式）+ 分发
│   ├── edit_common.py    # 共享：路径校验、原子写入、语法检查
│   ├── delete_common.py  # 共享：确认对话框 + 删除执行
│   ├── read_file.py      # read_file 工具
│   ├── list_dir.py       # list_dir 工具
│   ├── write_file.py     # write_file 工具
│   ├── str_replace.py    # str_replace 工具
│   ├── file_rewrite.py   # file_rewrite 工具
│   ├── make_dir.py       # make_dir 工具
│   ├── delete_file.py    # delete_file 工具
│   ├── delete_dir.py     # delete_dir 工具
│   ├── check_permissions.py  # check_permissions 工具
│   └── dummy.py          # echo 工具
├── logger.py             # 基于 Socket 的日志器（发送至日志服务器）
└── log_server.py         # TCP 日志服务器，用于实时调试输出
```

## 架构

Agent 分三层构建：

**CLI 层**（`cli/`）— REPL 入口。收集用户输入，驱动流式循环，通过 Rich 渲染输出。

**核心层**（`core/`）— 有状态的 ReAct 循环。在 `ConversationState` 中管理对话历史，使用工具定义调用 OpenAI API，并将工具调用路由回工具注册表，直到模型发出完成信号。

**工具层**（`tools/`）— 独立的工具实现。每个工具返回纯字符串（成功消息或错误）。注册表将工具名称映射到可调用对象，并用异常处理器包裹执行，确保错误不会导致循环崩溃。

**权限层**（`permissions/`）位于核心循环与删除工具之间，维护一个会话级已授权路径集合，在任何危险操作前进行检查。

## 测试

```bash
uv run pytest
```

测试文件位于 `tests/` 目录。删除权限系统具有最完整的测试覆盖（`tests/test_delete_permissions.py`）。

## 许可证

MIT

# CLI Agent

> **Language / 语言**: [English](#cli-agent-english) | [中文](#cli-agent-中文)

---

<a id="cli-agent-english"></a>

A CLI agent built from scratch in Python, implementing the ReAct (Reasoning + Acting) pattern. An interactive coding assistant that reads files, edits code, manages directories, and safely handles destructive operations—all from the terminal with streaming output. Includes a persistent memory system that tracks projects, summarizes sessions, and builds up context across conversations.

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
| `GPT_ENDPOINT` | `https://search.bytedance.net/gpt/openapi/online/v2/crawl` | ByteDance API base URL |
| `GPT_MODEL` | — | Overrides model when using ByteDance |
| `MEMORY_DIR` | `./agent-memory` | Directory for persistent memory storage |
| `LOG_DEBUG` | `false` | `true` = stream model response tokens to logs |
| `LOG_LEVEL` | `DEBUG` | Log level: DEBUG, INFO, WARNING, ERROR |
| `LOG_SERVER_PORT` | `9999` | Port for log-server |

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

### Persistent Memory

The agent remembers context across sessions using a local JSON store (`agent-memory/`).

**At startup**, the agent checks if the current directory is a known project:
- If recognized, it resumes the project and injects recent session digests + learnings into the system prompt.
- If new, it offers to onboard: scanning the directory, classifying the project with the LLM (tags, capabilities), and seeding from similar past projects.
- You can also link to an existing project or skip entirely.

**During the session**, every user and assistant turn is recorded.

**On exit**, a background subprocess generates a digest of the conversation (summary, learnings, capability updates) so the main process exits immediately without waiting.

**Memory commands** (type in the agent REPL):

| Command | Description |
|---------|-------------|
| `/memory show` | Show current project context and recent digest |
| `/memory projects` | List all tracked projects |
| `/memory init` | Onboard the current directory as a new project |
| `/memory clear learnings` | Clear accumulated learnings for the current project |
| `/memory personality show` | Show the agent's current personality |
| `/memory personality set soul "<text>"` | Update the agent's soul |
| `/memory personality set core "<text>"` | Update the agent's immutable core |
| `/memory help` | Show all memory commands |

### Permission System for Destructive Operations

Delete operations (`delete_file`, `delete_dir`) are protected by a session-scoped permission gate:

1. **First deletion attempt** on a path opens an interactive confirmation panel
2. User chooses from three options:
   - **Grant permission** — approve this path and all children for the rest of the session
   - **Delete once** — approve this single deletion only
   - **Cancel** — abort the operation
3. Granted permissions persist in memory for the session; parent-path grants cover all children

### Safety Features

- **Path validation**: All write and edit operations are confined to the current working directory.
- **Atomic writes**: File writes go to a temp file first, then atomically renamed — no partial writes on failure.
- **Syntax checking**: After editing Python or JSON files, the agent validates syntax and surfaces warnings.
- **Non-TTY safe**: Delete confirmation defaults to "cancel" when stdin is not a terminal.

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
│   ├── app.py            # Main entry point — REPL loop, project resolution, memory integration
│   └── display.py        # Rich UI: banner, prompts, streaming, delete confirm
├── config/
│   └── settings.py       # Settings dataclass, .env loading, validation
├── core/
│   ├── loop.py           # ReAct agent loop (streaming + non-streaming)
│   ├── state.py          # Conversation state — message history management
│   └── compaction.py     # Context compaction
├── memory/
│   ├── manager.py        # MemoryManager facade — single entry point for app
│   ├── store.py          # Local JSON file store (projects, digests, sessions, personality)
│   ├── models.py         # Pydantic models: Personality, Project, SessionDigest, ActiveSession
│   ├── session.py        # Session lifecycle: start, record turns, dispatch digest on exit
│   ├── digest_worker.py  # Background subprocess: generate and save session digest
│   ├── digest.py         # LLM digest derivation and learnings merging
│   ├── context.py        # Assemble memory context string for system prompt
│   ├── onboarding.py     # Project detection: scan cwd, classify with LLM, seed from similar
│   ├── personality.py    # Personality feedback extraction and soul patching
│   ├── commands.py       # /memory slash command handlers
│   ├── llm.py            # LLMClient protocol + RealLLMClient + MockLLMClient
│   ├── prompts.py        # All LLM prompt templates
│   ├── config.py         # MemoryConfig dataclass
│   └── tokens.py         # Token counting and truncation utilities
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

The agent is built in four layers:

**CLI layer** (`cli/`) — REPL entry point. Resolves the current project via memory, collects user input, drives the streaming loop, and renders output via Rich.

**Core layer** (`core/`) — Stateful ReAct loop. Manages conversation history in `ConversationState`, calls the OpenAI API with tool definitions, and routes tool calls back through the tool registry until the model signals it is done.

**Memory layer** (`memory/`) — Persistent context across sessions. Tracks projects by working directory, records every conversation turn, and generates session digests in a detached background process on exit. The assembled context (personality, project info, last digest, learnings) is injected into the system prompt at startup.

**Tools layer** (`tools/`) — Self-contained tool implementations. Each tool returns a plain string (success message or error). The registry maps tool names to callables and wraps execution in exception handlers so errors never crash the loop.

The **permissions layer** (`permissions/`) sits between the core loop and the delete tools, maintaining a session-level set of granted paths checked before any destructive operation.

## Testing

```bash
uv run pytest
```

Tests live in `tests/`. Coverage includes the full memory subsystem (store, session lifecycle, digest generation, onboarding, personality, commands) and the delete permission system.

## License

MIT

---

<a id="cli-agent-中文"></a>

# CLI Agent 中文

> **Language / 语言**: [English](#cli-agent-english) | [中文](#cli-agent-中文)

一个从零开始用 Python 构建的命令行智能体，实现了 ReAct（推理 + 行动）模式。这是一个交互式编程助手，可以读取文件、编辑代码、管理目录，并安全处理危险操作——全部在终端中以流式输出的方式进行。内置持久化记忆系统，可跨会话追踪项目、归纳对话摘要并积累上下文。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐）
- OpenAI API 密钥 **或** 字节跳动 GPT API 密钥（`GPT_AK`）

## 安装配置

1. 克隆仓库并安装依赖：

```bash
uv sync
```

2. 在项目根目录创建 `.env` 文件，选择以下之一：

**方案 A — OpenAI：**
```
OPENAI_API_KEY=your-api-key-here
```

**方案 B — 字节跳动 GPT：**
```
GPT_AK=your-bytedance-api-key
```

可选环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_MODEL` | `gpt-4o-mini` | 使用的模型 |
| `OPENAI_MAX_TOKENS` | `4096` | 最大补全 token 数 |
| `MEMORY_DIR` | `./agent-memory` | 持久化记忆存储目录 |

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

### 持久化记忆系统

Agent 通过本地 JSON 存储（`agent-memory/`）在会话间保留上下文。

**启动时**，Agent 检查当前目录是否为已知项目：
- 若已识别，自动恢复项目，并将最近的会话摘要和学习内容注入系统提示。
- 若为新目录，提示进行项目导入：扫描目录、用 LLM 分类项目（标签、能力），并从相似历史项目中继承能力。
- 也可链接到已有项目，或跳过记忆功能。

**会话中**，每条用户和助手消息都会被记录。

**退出时**，后台子进程自动生成会话摘要（摘要、学习内容、能力更新），主进程无需等待即可退出。

**记忆命令**（在 agent REPL 中输入）：

| 命令 | 说明 |
|------|------|
| `/memory show` | 显示当前项目上下文和最近摘要 |
| `/memory projects` | 列出所有已追踪项目 |
| `/memory init` | 将当前目录导入为新项目 |
| `/memory clear learnings` | 清除当前项目的学习内容 |
| `/memory personality show` | 显示 agent 当前的个性 |
| `/memory personality set soul "<text>"` | 更新 agent 的灵魂 |
| `/memory personality set core "<text>"` | 更新 agent 的不可变核心 |
| `/memory help` | 显示所有记忆命令 |

### 危险操作权限系统

删除操作（`delete_file`、`delete_dir`）受会话级权限门控保护：

1. **首次删除**某路径时，会打开交互式确认面板
2. 用户可从三个选项中选择：
   - **授予权限** — 批准该路径及其所有子路径在本次会话中的删除权限
   - **仅此一次** — 仅批准本次删除操作
   - **取消** — 中止操作
3. 授予的权限在会话期间保留；对父路径的授权覆盖所有子路径

### 安全特性

- **路径校验**：所有写入和编辑操作限制在当前工作目录内。
- **原子写入**：文件写入先写入临时文件，再原子性重命名——失败时不会产生残缺文件。
- **语法检查**：编辑 Python 或 JSON 文件后，agent 会验证语法并显示警告。
- **非 TTY 安全**：当 stdin 不是终端时，删除确认默认为"取消"。

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
│   ├── app.py            # 主入口 — REPL 循环、项目解析、记忆集成
│   └── display.py        # Rich UI：横幅、提示、流式输出、删除确认
├── config/
│   └── settings.py       # 配置数据类，.env 加载与校验
├── core/
│   ├── loop.py           # ReAct agent 循环（流式与非流式）
│   ├── state.py          # 对话状态 — 消息历史管理
│   └── compaction.py     # 上下文压缩
├── memory/
│   ├── manager.py        # MemoryManager 门面 — app 的单一入口
│   ├── store.py          # 本地 JSON 文件存储（项目、摘要、会话、个性）
│   ├── models.py         # Pydantic 模型：Personality、Project、SessionDigest、ActiveSession
│   ├── session.py        # 会话生命周期：开始、记录轮次、退出时分发摘要
│   ├── digest_worker.py  # 后台子进程：生成并保存会话摘要
│   ├── digest.py         # LLM 摘要推导与学习内容合并
│   ├── context.py        # 组装记忆上下文字符串注入系统提示
│   ├── onboarding.py     # 项目检测：扫描目录、LLM 分类、从相似项目继承
│   ├── personality.py    # 个性反馈提取与灵魂更新
│   ├── commands.py       # /memory 斜杠命令处理
│   ├── llm.py            # LLMClient 协议 + RealLLMClient + MockLLMClient
│   ├── prompts.py        # 所有 LLM 提示模板
│   ├── config.py         # MemoryConfig 数据类
│   └── tokens.py         # Token 计数与截断工具
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

Agent 分四层构建：

**CLI 层**（`cli/`）— REPL 入口。通过记忆系统解析当前项目，收集用户输入，驱动流式循环，并通过 Rich 渲染输出。

**核心层**（`core/`）— 有状态的 ReAct 循环。在 `ConversationState` 中管理对话历史，使用工具定义调用 OpenAI API，并将工具调用路由回工具注册表，直到模型发出完成信号。

**记忆层**（`memory/`）— 跨会话的持久化上下文。按工作目录追踪项目，记录每条对话轮次，并在退出时通过独立后台进程生成会话摘要。启动时将组装好的上下文（个性、项目信息、最近摘要、学习内容）注入系统提示。

**工具层**（`tools/`）— 独立的工具实现。每个工具返回纯字符串（成功消息或错误）。注册表将工具名称映射到可调用对象，并用异常处理器包裹执行，确保错误不会导致循环崩溃。

**权限层**（`permissions/`）位于核心循环与删除工具之间，维护一个会话级已授权路径集合，在任何危险操作前进行检查。

## 测试

```bash
uv run pytest
```

测试文件位于 `tests/` 目录。覆盖完整的记忆子系统（存储、会话生命周期、摘要生成、项目导入、个性、命令）以及删除权限系统。

## 许可证

MIT

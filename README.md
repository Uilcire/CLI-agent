# CLI Agent

> **Language / 语言**: [English](#cli-agent-english) | [中文](#cli-agent-中文)

---

<a id="cli-agent-english"></a>

A CLI agent built from scratch in Python, implementing the ReAct (Reasoning + Acting) pattern. An interactive coding assistant that reads files, edits code, manages directories, and safely handles destructive operations — all from the terminal with streaming output. Includes a markdown-native **assistant memory** layer that mirrors `CLAUDE.md`-style notes, retrieves relevant context per turn via two-stage LLM selection, and evolves the agent's "soul" through inline `[memory note: ...]` markers.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended)
- An OpenAI API key, a ByteDance GPT API key (`GPT_AK`), **or** a DeepSeek API key (`DEEPSEEK_API_KEY`)

## Setup

1. Clone the repo and install dependencies:

```bash
uv sync
```

2. Create a `.env` file in the project root. **Either** OpenAI **or** ByteDance GPT **or** DeepSeek:

**Option A — OpenAI:**
```
OPENAI_API_KEY=your-api-key-here
```

**Option B — ByteDance GPT** (uses Azure-compatible API):
```
GPT_AK=your-bytedance-api-key
```

**Option C — DeepSeek** (OpenAI-compatible API):
```
DEEPSEEK_API_KEY=your-deepseek-api-key
```

Auto-detect priority when no `USE_*` flag is set: **DeepSeek → ByteDance → OpenAI**.

Optional env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_DEEPSEEK` | auto | `true` forces DeepSeek (requires `DEEPSEEK_API_KEY`) |
| `USE_BYTEDANCE` | auto | `true` = ByteDance, `false` = fall through to DeepSeek/OpenAI |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model to use for OpenAI |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | Default DeepSeek model (legacy) |
| `DEEPSEEK_MODEL_PRO` | `deepseek-v4-pro` | Large model: main responses + curator judgment |
| `DEEPSEEK_MODEL_FLASH` | `deepseek-v4-flash` | Small/fast model: two-stage memory retrieval |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API base URL |
| `OPENAI_MAX_TOKENS` | `4096` | Max completion tokens |
| `GPT_ENDPOINT` | `https://search.bytedance.net/gpt/openapi/online/v2/crawl` | ByteDance API base URL |
| `GPT_MODEL` | `gpt-5.2-2025-12-11` | Overrides model when using ByteDance |
| `ASSISTANT_MEMORY_DIR` | `~/assistant-memory` | Markdown memory store root |
| `LOG_DEBUG` | `false` | `true` = stream model response tokens to logs |
| `LOG_LEVEL` | `DEBUG` | Log level: DEBUG, INFO, WARNING, ERROR |
| `LOG_SERVER_PORT` | `9999` | Port for log-server |

## Running

```bash
uv run agent
```

Pass `-memlog` (or `--memlog`) to render memory subsystem events as orange `🧠 MEMORY` panels alongside tool calls — handy for understanding what the retrieval and curator layers are doing in real time:

```bash
uv run agent -memlog
```

For live debug logging, start the log server in a separate terminal before launching the agent:

```bash
uv run log-server
```

Type your message and press Enter. Use `quit`, `exit`, or Ctrl+C to leave. Press Ctrl+C twice in rapid succession to force-exit (skips finally and aborts in-flight curator/digest threads).

---

## Features

### Streaming ReAct Loop

The agent reasons, calls tools, observes results, and repeats until the task is complete. All output streams in real time: text tokens, tool invocations, and tool results.

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
| `web_search` | Utility | Web search for facts and verification |
| `read_skill` | Utility | Load a skill's full instructions into context |

### Assistant Memory

The agent maintains a **markdown-native** memory store at `~/assistant-memory/` (override with `ASSISTANT_MEMORY_DIR`). The layout mirrors `CLAUDE.md`-style human-readable notes — no JSON shadow store, no embeddings.

```
~/assistant-memory/
├── _index.md                   # top-level manifest (always read at startup)
├── identity/
│   ├── _manifest.md
│   ├── me.md                   # the user's identity
│   └── agent.md                # agent's soul; frontmatter holds immutable_core
├── people/<name>.md            # one file per person
├── preferences/<topic>.md      # food, coffee, reading, gifts, travel, …
├── projects/<project>.md       # frontmatter has cwd, status, tags
├── context/current.md          # this week's state — always injected
└── log/YYYY-MM/YYYY-MM-DD.md   # daily session digests; monthly summaries in _manifest
```

**Per-turn retrieval (read side).** Before each model call:
1. `_index.md` + recent turns + the user query feed a Stage-1 LLM (`deepseek-v4-flash`) that picks scopes (`people`, `preferences`, `projects`, `log`).
2. Selected scope manifests feed a Stage-2 LLM that picks up to 5 specific files.
3. Those files plus `context/current.md` are injected as a transient system suffix for that turn only — never polluting conversation history.

**Curator (write side).** After each assistant reply, a background daemon thread runs the curator (`deepseek-v4-pro`):
- Scans the user message for declarative facts and the assistant reply for `[memory note: ...]` markers.
- Layer 1 (silent): trivial extractions (e.g. "I'm allergic to peanuts" → append to `preferences/food.md`).
- Layer 2 (confirm): ambiguous or contradicting facts. *(Confirm callback is currently a no-op — Layer 2 silently skipped pending UI work.)*
- Updates the affected manifest line incrementally.

**On exit.** A consolidation pass + per-day session digest run in a daemon thread. The agent prints `Dreaming...` and exits. The most recent per-turn curator is joined for up to 2s before consolidation runs so manifests aren't read stale.

**Soul evolution.** The agent's mutable "soul" lives in the body of `identity/agent.md`. The immutable values (frontmatter `immutable_core`) are always appended to the system prompt — they never depend on retrieval. Soul updates flow through the curator's `[memory note: ...]` channel.

**Slash commands** (type in the agent REPL):

| Command | Description |
|---------|-------------|
| `/memory list <scope>` | List files in a scope (e.g. `people`, `projects`) |
| `/memory show <scope>/<file>` | Print a memory file with frontmatter |
| `/memory rebuild <scope>` | Regenerate a scope manifest from scratch |
| `/memory current` | Show `context/current.md` |
| `/memory help` | Show all memory commands |
| `/skills` | List installed skills |
| `/<skill-name>` | Load a skill's instructions into context |

**Migration from the old JSON store.** If you have a legacy `agent-memory/` directory from a prior version, run:

```bash
uv run python -m scripts.migrate_to_assistant_memory
```

The script converts `personality.json` → `identity/agent.md`, projects + digests → markdown, and renames the old dir to `agent-memory.legacy/`.

### Permission System for Destructive Operations

Delete operations (`delete_file`, `delete_dir`) are protected by a session-scoped permission gate:

1. **First deletion attempt** on a path opens an interactive confirmation panel
2. User chooses from three options:
   - **Grant permission** — approve this path and all children for the rest of the session
   - **Delete once** — approve this single deletion only
   - **Cancel** — abort the operation
3. Granted permissions persist in memory for the session; parent-path grants cover all children

### Safety Features

- **Path validation**: Edit operations are confined to the current working directory.
- **Atomic writes**: File writes go to a temp file then atomically renamed.
- **Syntax checking**: After editing Python or JSON files, the agent validates syntax.
- **Non-TTY safe**: Delete confirmation defaults to "cancel" when stdin is not a terminal.

### Rich Terminal UI

- Startup banner with project name and version
- Color-coded output: user prompts in green, tool calls with `⟳ tool_name(args)`, MEMORY panels in orange (with `-memlog`), errors in red
- Streaming markdown rendering for assistant replies; `[memory note: ...]` markers stripped inline before they reach the screen
- Live log server for debug output without polluting the agent REPL

---

## Project Structure

```
src/agent/
├── cli/
│   ├── app.py            # REPL loop, project resolution, retrieval injection
│   └── display.py        # Rich UI: banner, prompts, streaming, MEMORY panels
├── config/
│   └── settings.py       # Settings dataclass, .env loading, validation
├── core/
│   ├── loop.py           # ReAct loop (consumes ConversationState transient suffix)
│   ├── state.py          # Conversation state — message history + per-turn suffix
│   └── compaction.py     # Context compaction
├── assistant_memory/
│   ├── manager.py        # AssistantMemoryManager — public lifecycle entry points
│   ├── store.py          # markdown + frontmatter IO, atomic writes, glob helpers
│   ├── schema.py         # frontmatter parse/dump, dataclasses, get_memory_dir()
│   ├── prompts.py        # Stage-1, Stage-2, main-response, curator prompt templates
│   ├── retrieval.py      # Two-stage retrieval pipeline
│   └── curator.py        # extract notes, classify layer, apply writes, summarize sessions
├── permissions/
│   └── gates.py          # Session-scoped delete permission tracking
├── skills/               # Skill discovery + manager (Claude Code-style)
├── tools/                # Tool implementations (read/write/edit/delete + utilities)
├── logger.py             # Socket-based logger (sends to log server)
└── log_server.py         # TCP log server for live debug output
scripts/
└── migrate_to_assistant_memory.py  # one-shot legacy JSON → markdown migration
```

## Architecture

The agent is built in five layers:

**CLI layer** (`cli/`) — REPL entry point. Resolves the current project via `AssistantMemoryManager`, collects user input, runs per-turn retrieval, drives the streaming loop, and renders output via Rich.

**Core layer** (`core/`) — Stateful ReAct loop. Manages conversation history in `ConversationState`, calls the model with tool definitions, and routes tool calls back through the tool registry until the model signals it is done. `ConversationState.set_transient_system_suffix(...)` lets the memory layer inject retrieval results for one turn without persisting them.

**Assistant memory layer** (`assistant_memory/`) — Markdown-native memory. Two-stage LLM retrieval on the read side, a per-turn curator daemon plus on-exit consolidation + digest on the write side. Public surface preserved as `on_startup`, `on_user_turn`, `on_assistant_turn`, `on_exit`, `find_project_for_cwd`, `onboard_for_cwd`, `onboard`, `handle_command`, `retrieve_for_query`.

**Tools layer** (`tools/`) — Self-contained tool implementations.

**Permissions layer** (`permissions/`) — Session-scoped delete permission tracking.

## Testing

```bash
uv run pytest -q
```

Tests live in `tests/`. Coverage includes the assistant memory store, retrieval pipeline, curator, manager wiring, slash commands, the delete permission system, and the streaming display layer's `[memory note: ...]` filter.

## License

MIT

---

<a id="cli-agent-中文"></a>

# CLI Agent 中文

> **Language / 语言**: [English](#cli-agent-english) | [中文](#cli-agent-中文)

一个从零开始用 Python 构建的命令行智能体，实现了 ReAct（推理 + 行动）模式。这是一个交互式编程助手，可以读取文件、编辑代码、管理目录，并安全处理危险操作——全部在终端中以流式输出的方式进行。内置 **markdown 原生的助手记忆系统**，目录结构镜像 `CLAUDE.md` 风格的人类可读笔记，每轮对话通过两阶段 LLM 选择检索相关上下文，并通过 `[memory note: ...]` 标记演化 agent 的"灵魂"。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐）
- OpenAI API 密钥、字节跳动 GPT API 密钥（`GPT_AK`），**或** DeepSeek API 密钥（`DEEPSEEK_API_KEY`）

## 安装

```bash
uv sync
```

在项目根目录创建 `.env`，三选一即可（自动检测优先级：DeepSeek → ByteDance → OpenAI）：

```
OPENAI_API_KEY=...
GPT_AK=...
DEEPSEEK_API_KEY=...
```

可选环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USE_DEEPSEEK` | auto | `true` 强制使用 DeepSeek |
| `USE_BYTEDANCE` | auto | `true` 强制使用 ByteDance |
| `DEEPSEEK_MODEL_PRO` | `deepseek-v4-pro` | 主回复 + 整理判断的大模型 |
| `DEEPSEEK_MODEL_FLASH` | `deepseek-v4-flash` | 两阶段记忆检索的小模型 |
| `ASSISTANT_MEMORY_DIR` | `~/assistant-memory` | markdown 记忆库根目录 |

## 运行

```bash
uv run agent           # 普通运行
uv run agent -memlog   # 显示橙色 🧠 MEMORY 面板（检索/整理/摘要事件）
```

输入消息后按 Enter 发送。使用 `quit`、`exit` 或 Ctrl+C 退出；连按两次 Ctrl+C 强制退出（跳过 finally，中止后台 curator/digest 线程）。

## 助手记忆系统

记忆库位于 `~/assistant-memory/`：

```
~/assistant-memory/
├── _index.md                   # 顶层 manifest，启动时总是读取
├── identity/
│   ├── me.md                   # 用户身份
│   └── agent.md                # agent 的灵魂；frontmatter 含 immutable_core
├── people/<name>.md            # 每个人物一个文件
├── preferences/<topic>.md      # 饮食、咖啡、阅读、礼物、旅行……
├── projects/<project>.md       # frontmatter 含 cwd、status、tags
├── context/current.md          # 本周状态 —— 永远注入
└── log/YYYY-MM/YYYY-MM-DD.md   # 每日会话摘要
```

**每轮检索（读侧）。** 模型调用之前：
1. `_index.md` + 最近几轮对话 + 用户问题 → Stage 1 小模型挑选 scope。
2. 选中 scope 的 manifest → Stage 2 小模型挑选最多 5 个文件。
3. 这些文件 + `context/current.md` 作为本轮的临时 system 后缀注入，**不污染对话历史**。

**整理器（写侧）。** 每轮助手回复后，后台守护线程运行 curator（大模型）：
- 扫描用户消息中的事实陈述、助手回复中的 `[memory note: ...]` 标记。
- Layer 1（静默）：明确的事实 → 直接 append 到对应文件。
- Layer 2（确认）：模糊或矛盾事实。*（确认 UI 暂未接入，目前 Layer 2 静默跳过。）*
- 增量更新对应 manifest 行。

**退出时。** 触发整理 + 当日会话摘要（后台守护线程）。退出前最近一次 per-turn curator 会被 join 最多 2 秒，避免整理读到过期 manifest。

**灵魂演化。** Agent 的可变"灵魂"在 `identity/agent.md` 的 body；不可变值（frontmatter `immutable_core`）每次启动都注入系统提示，不依赖检索。灵魂更新通过 `[memory note: ...]` 通道流入。

**斜杠命令：**

| 命令 | 说明 |
|------|------|
| `/memory list <scope>` | 列出 scope 内的文件 |
| `/memory show <scope>/<file>` | 显示某个记忆文件 |
| `/memory rebuild <scope>` | 重新生成 scope manifest |
| `/memory current` | 显示 `context/current.md` |
| `/memory help` | 显示所有记忆命令 |
| `/skills` | 列出已安装的 skill |
| `/<skill-name>` | 显式加载某个 skill |

**从旧 JSON 存储迁移：**

```bash
uv run python -m scripts.migrate_to_assistant_memory
```

把 `personality.json` 转换为 `identity/agent.md`，把 projects + digests 转换为 markdown，并将旧目录重命名为 `agent-memory.legacy/`。

## 测试

```bash
uv run pytest -q
```

## 许可证

MIT

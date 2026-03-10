# CLI Agent

A CLI agent built from scratch in Python, implementing the ReAct (Reasoning + Acting) pattern. An interactive coding assistant that reads files, edits code, manages directories, and safely handles destructive operations—all from the terminal with streaming output.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended)
- An OpenAI API key

## Setup

1. Clone the repo and install dependencies:

```bash
uv sync
```

2. Create a `.env` file in the project root:

```
OPENAI_API_KEY=your-api-key-here
```

Optional env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-5-mini-2025-08-07` | Model to use |
| `OPENAI_MAX_TOKENS` | `4096` | Max completion tokens |

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

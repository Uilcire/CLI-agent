# CLI Agent

A CLI agent built from scratch in Python. An interactive coding assistant that can read files, edit code, run commands, and explore your project—all from the terminal.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Setup

1. Clone the repo and install dependencies:

```bash
uv sync
```

2. Add your OpenAI API key. Create a `.env` file in the project root:

```
OPENAI_API_KEY=your-api-key-here
```

Optional env vars:
- `OPENAI_MODEL` — model to use (default: `gpt-5-mini-2025-08-07`)
- `OPENAI_MAX_TOKENS` — max completion tokens (default: 4096)

## Running

```bash
uv run agent
```

Type your message and press Enter. Use `quit` or `exit` to leave.

## Features

- **Streaming output** — model thinking, tool calls, and results stream in real time
- **ReAct loop** — the agent decides when to use tools and iterates until done

### Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `list_dir` | List directory contents |
| `write_file` | Create or overwrite a file |
| `str_replace` | Replace a unique string in a file (targeted edits) |
| `file_rewrite` | Overwrite entire file with new content |
| `make_dir` | Create a directory (and parent dirs if needed) |
| `echo` | Echo a message (for testing) |

## Project Structure

```
src/agent/
├── cli/          # REPL entry point, display, streaming
├── config/       # Settings, .env loading
├── core/         # ReAct agent loop, conversation state
└── tools/        # Tool registry and implementations
```

## License

MIT

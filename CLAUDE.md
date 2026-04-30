# CLI-Agent Project Context

A CLI agent (like Claude Code) built from scratch in Python.

## Architecture

- `src/agent/core/` — ReAct agent loop, conversation state, compaction
- `src/agent/tools/` — tool registry and individual tool implementations
- `src/agent/cli/` — REPL entry point and display/streaming layer
- `src/agent/permissions/` — safety gates and tier classification
- `src/agent/config/` — settings and CLAUDE.md-style context loading
- `src/agent/assistant_memory/` — manifest-based personal memory (retrieval + curator)
- `src/agent/memory/` — legacy: only `models.py` kept for migration script

## Memory Layout (NEW — replaces old `agent-memory/personality.json`)

The agent's personality, the user's identity, and all personal facts live in
`~/assistant-memory/` (override with `ASSISTANT_MEMORY_DIR` env). Layout:

| Path | What |
|---|---|
| `identity/agent.md` | **Agent's own soul (this is YOU).** Frontmatter `immutable_core` is locked. Body is mutable but only via curator Layer 2 (user must confirm). NEVER use `str_replace` here. |
| `identity/me.md` | User identity — stable facts about the user. User-maintained. Don't auto-edit. |
| `people/<name>.md` | Per-person notes. Curator Layer 1 may append facts. |
| `preferences/<topic>.md` | User preferences (food, coffee, gifts, ...). Curator may append. |
| `projects/<id>.md` | Project files; frontmatter has cwd/status/tags. |
| `context/current.md` | This week's state. **User-maintained, not LLM-edited.** |
| `log/YYYY-MM/YYYY-MM-DD.md` | Session digests, written by `curator.summarize_session` at session end. |
| `_index.md` | Top-level manifest with user one-liner. Always loaded. |
| `<scope>/_manifest.md` | Scope manifest — pipe-delimited hooks for retrieval Stage 1/2. |

**Migration**: legacy `agent-memory/` was archived to `agent-memory.legacy/` by
`scripts/migrate_to_assistant_memory.py`. The old `personality_edit` tool is
gone — soul changes go through the curator (`[memory note: ...]` markers).

**Retrieval is two-stage** (`assistant_memory/retrieval.py`):
1. Stage 1 picks scopes from `_index.md` (model: `deepseek-v4-flash`).
2. Stage 2 picks ≤5 files from those scopes' manifests (same model).
3. Main response uses retrieved files + `current.md` + `agent.md` + `me.md` (model: `deepseek-v4-pro`).

**Curator** runs in a daemon thread after each assistant turn — extracts facts
and appends to memory. Session-end digest is written by `on_exit()`.

## Build Phases

1. **Phase 1** — Skeleton loop + minimal CLI (one dummy tool, no hardening)
2. **Phase 2** — Tools (read-only first, then write tools)
3. **Phase 3** — Harden: compaction, permission tiers, circuit breakers, streaming UX

## Running

```bash
# Add OPENAI_API_KEY to .env
uv sync
uv run agent
```

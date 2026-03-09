# CLI-Agent Project Context

A CLI agent (like Claude Code) built from scratch in Python.

## Architecture

- `src/agent/core/` — ReAct agent loop, conversation state, compaction
- `src/agent/tools/` — tool registry and individual tool implementations
- `src/agent/cli/` — REPL entry point and display/streaming layer
- `src/agent/permissions/` — safety gates and tier classification
- `src/agent/config/` — settings and CLAUDE.md-style context loading

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

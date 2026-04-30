# Assistant Memory System — Design Doc (Phase 1)

> Authoritative reference for all implementation agents. Read this fully before writing code.

## Goal

A personal-assistant memory layer that answers 80% of personal queries using **pure markdown + manifests + LLM file selection** — no embeddings, no graph. If this layer doesn't work, graph won't save it.

## Decisions (locked)

- **D1**: Markdown is the **only** truth source. No JSON shadow store. Structured fields go in YAML frontmatter.
- **D2**: `immutable_core` (agent's hard-coded values) lives in `identity/agent.md` frontmatter `immutable: true`, **always** appended to system prompt — never depends on retrieval.
- **D3**: Keep cwd-based auto-onboarding behavior. Output now is `projects/<id>.md` instead of JSON.
- **D4**: One-shot migration script converts existing `agent-memory/` JSON → new markdown layout. Old dir archived as `agent-memory.legacy/`.
- **D5**: `MemoryManager` is **replaced** (not facaded). Public interface for `cli/app.py` should preserve method names (`on_startup`, `on_user_turn`, `on_assistant_turn`, `on_exit`, `find_project_for_cwd`, `onboard_for_cwd`, `onboard`, `handle_command`) but the internals are entirely new.
- **No embeddings**. Two-stage LLM retrieval (scope select → file select) only.
- **Dual model**: small/fast for retrieval Stage 1+2 = `deepseek-v4-flash`; large for main response + curator judgment = `deepseek-v4-pro`.

## Directory Layout

```
~/assistant-memory/             # default; ASSISTANT_MEMORY_DIR overrides
├── _index.md                   # top-level manifest, always read by Stage 1
├── identity/
│   ├── _manifest.md
│   ├── me.md                   # user identity
│   └── agent.md                # agent soul; frontmatter immutable_core
├── people/
│   ├── _manifest.md
│   └── <name>.md
├── preferences/
│   ├── _manifest.md
│   └── <topic>.md              # food, coffee, reading, gifts, travel, ...
├── projects/
│   ├── _manifest.md
│   └── <project_id>.md         # frontmatter has cwd, status, tags
├── context/
│   └── current.md              # ALWAYS read; not in any manifest; curator may edit
└── log/
    ├── _manifest.md            # monthly summary, NOT per-day index
    └── 2026-04/
        └── 2026-04-29.md
```

## File Format

Every file (except `_index.md` and manifests) is markdown with YAML frontmatter:

```markdown
---
name: alex
type: person
relation: girlfriend
since: 2024
location: SF
last_updated: 2026-04-29
---

# Alex

(free-form markdown body)
```

`projects/<id>.md` frontmatter must include: `project_id`, `cwd`, `status` (active|paused|complete), `tags`, `capabilities`, `last_summarized_session`. Body has sections `## Description`, `## Learnings`, `## Recent Sessions`.

`identity/agent.md` frontmatter: `immutable_core: |` (multiline string). Body is the mutable soul.

## Manifest Formats

### `_index.md` (top-level)

```markdown
---
user_summary: "Eric — CS student, ByteDance intern in Singapore researching AI agents."
last_rebuilt: 2026-04-29
---

# Memory Index

## Scopes
- **identity/** — Who I am + agent's own soul
- **people/** — N people tracked: <name1>, <name2>, ...
- **preferences/** — N preference areas: food, coffee, ...
- **projects/** — N active: <p1>, <p2>, ...
- **context/current.md** — This week's state (always read)
- **log/** — Event history, monthly summaries available
```

### `people/_manifest.md`

```markdown
# People Manifest
Last rebuilt: 2026-04-29

- **alex.md** | Girlfriend, since 2024 | SF | EM at Stripe (since Apr 2026) | allergic to shellfish | wants Kyoto trip in fall
- **mom.md**  | Mother | Shanghai | retired teacher | recovering from knee surgery (Apr 2026) | calls weekly
```

One person per line, pipe-delimited, key attrs first, time anchors **inline and absolute** (never "recently"). Include open threads (hooks for future recall). Don't store full facts — manifest is a hook, file is the source.

### `preferences/_manifest.md`

```markdown
# Preferences Manifest

- **food.md** | dietary restrictions, cuisines I like, eating-out habits
- **coffee.md** | brewing setup, beans, drink preferences
- **reading.md** | genres, authors, current reading list
- **gifts.md** | how I think about giving gifts, budget norms
- **travel.md** | travel style, hotel preferences, packing habits
```

One file per line, **describes the kind of info inside**, not the info itself.

### `projects/_manifest.md`

```markdown
# Projects Manifest

- **cli-agent.md** | active | CLI agent built from scratch | cwd:/Users/bytedance/Projects/CLI-agent | tags: python, agents
- **memact-research.md** | active | MemAct paper deep-dive | tags: research
```

### `log/_manifest.md`

Monthly summaries only — never per-day entries:

```markdown
# Log Manifest

## 2026-04 (current month)
- Mom's surgery recovery, weekly calls
- Alex job change to Stripe
- Started CLI agent project Phase 2

## 2026-03
- Trip to Tokyo with Alex
- ...
```

## Retrieval Pipeline

### Stage 1: Scope Selection (deepseek-v4-flash)

Input: user query + recent 3 turns + `_index.md`.
Output: JSON `{"scopes": [...], "reasoning": "..."}`.
Always include `context/current.md` implicitly (not via this stage).

### Stage 2: File Selection (deepseek-v4-flash)

Input: user query + recent 3 turns + manifests of selected scopes.
Output: JSON `{"files": [...], "reasoning": "..."}`.
Cap: 5 files total. "Be aggressive about exclusion."

### Stage 3: Main Response (deepseek-v4-pro)

System prompt = `identity/agent.md` immutable_core (frontmatter) + soul (body) + user one-liner from `_index.md` + `context/current.md` + selected file contents.

User message ends with: "If you notice something that should update memory, mention it briefly at the end as: `[memory note: ...]`"

## Curator (write side)

Two layers:

1. **Silent write (Layer 1)**: trivial extractions (e.g., user said "I'm allergic to peanuts" → append to `preferences/food.md`). Done by curator agent (deepseek-v4-pro) post-turn, no user confirmation.
2. **Confirm write (Layer 2)**: ambiguous or contradicting facts → present to user before writing.

### Curator triggers

- After every assistant turn: scan assistant output for `[memory note: ...]` markers AND scan user message for declarative facts.
- Curator decides: which scope, which file (or new file), Layer 1 vs Layer 2.

### Manifest incremental update

After each write, curator reads the affected manifest line, decides if write changed manifest-relevant info (location, role, open thread, etc.), updates that one line if so. Never rewrites whole manifest.

`rebuild_manifest(scope)` exists as a separate function for full regeneration on demand.

### Session digest → log

At session end (replaces old `digest_worker.py` flow):
1. Curator summarizes the session into a daily log file `log/YYYY-MM/YYYY-MM-DD.md` (append).
2. If session was project-scoped, append condensed learnings to `projects/<id>.md` Learnings section.
3. Update `log/_manifest.md` monthly summary if material changes occurred.

## Migration (one-shot)

Script: `scripts/migrate_to_assistant_memory.py`

For each old artifact:
- `personality.json` → `identity/agent.md` (soul → body, immutable_core → frontmatter)
- `projects/<id>.json` → `projects/<id>.md` with frontmatter
- `digests/*.json` → bucket by date into `log/YYYY-MM/YYYY-MM-DD.md`; condensed lines into matching `projects/<id>.md` Learnings
- Stub create: `identity/me.md` (empty user identity), `context/current.md` (empty), `_index.md` (auto from scope dirs)
- After success: rename old `agent-memory/` → `agent-memory.legacy/`

## Settings

Add to `Settings` dataclass:
- `model_pro: str` — defaults to `DEEPSEEK_MODEL_PRO` env or `deepseek-v4-pro`
- `model_flash: str` — defaults to `DEEPSEEK_MODEL_FLASH` env or `deepseek-v4-flash`

Existing `model` field stays as the legacy default.

## Module Layout

```
src/agent/assistant_memory/
├── __init__.py
├── schema.py        # dataclasses: PersonFile, ProjectFile, Manifest, RetrievalResult; YAML frontmatter helpers
├── store.py         # markdown + frontmatter IO, atomic writes, glob helpers
├── prompts.py       # 4 prompts: STAGE1_SCOPE, STAGE2_FILE, MAIN_RESPONSE, CURATOR
├── retrieval.py     # two-stage retrieve(query, recent_turns) -> list[Path] of files
├── curator.py       # extract_notes, classify_layer, write_fact, update_manifest_line, summarize_session
├── manager.py       # AssistantMemoryManager — replaces MemoryManager, same public interface
└── migrate.py       # one-shot migration
```

## Test Targets

`tests/test_assistant_memory/`:
- `test_store.py` — frontmatter roundtrip, atomic write
- `test_retrieval.py` — mock LLM, verify Stage 1/2 selection on 10 spec queries
- `test_curator.py` — `[memory note]` parsing, manifest line update, layer classification
- `test_migrate.py` — fixture old `agent-memory/` → assert new layout
- `test_e2e.py` — happy path with mock LLMs

## 10 Validation Queries

(from spec — drive retrieval correctness target ≥80% file-level)

1. "Alex 生日什么时候？"
2. "下次见 mom 该带什么礼物？"
3. "我最近在做什么项目？"
4. "我喜欢喝什么咖啡？"
5. "上个月我去了哪？"
6. "Jamie 最近怎么样？"
7. "我应该给 Sam 推荐什么餐厅？"
8. "我去年这时候在做什么？"
9. "我想去 Kyoto 是和谁说的？"
10. "我现在正在 deep-dive 哪篇论文？"

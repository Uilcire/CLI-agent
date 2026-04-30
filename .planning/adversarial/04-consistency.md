# Doc/Code Consistency — Drift Findings

Scope: cross-check `CLAUDE.md`, `.planning/assistant-memory-design.md`, `README.md`,
`src/agent/assistant_memory/**`, `scripts/migrate_to_assistant_memory.py`,
`src/agent/cli/{app,display}.py`, `src/agent/memory/`, `src/agent/permissions/`,
`src/agent/tools/registry.py`, and the test suite. Read-only review.

Anchors:
- CLAUDE.md is short and recently updated; mostly aligned with code.
- Design doc is authoritative; code follows it but with several silent deviations.
- README.md is **deeply stale** — it still describes the deleted JSON memory
  system, deleted `digest_worker.py`, deleted `personality_edit` tool family, and
  the entire deleted `memory/` package layout. It is the single biggest drift
  surface in the repo.

---

## CRITICAL (will mislead any new reader)

### D1. README.md describes a memory subsystem that no longer exists
- **Doc**: `README.md:106-129` (English) and `README.md:331-355` (中文).
- **Claim**: "The agent remembers context across sessions using a local JSON store
  (`agent-memory/`)" — lists `/memory show`, `/memory projects`, `/memory init`,
  `/memory clear learnings`, `/memory personality show`, `/memory personality set
  soul`, `/memory personality set core`, `/memory help` as the supported memory
  commands. Documents `MEMORY_DIR=./agent-memory` as the env var.
- **Reality**: The new `AssistantMemoryManager.handle_command` (manager.py:291-341)
  exposes only `/memory list`, `/memory show <scope>/<file>`, `/memory rebuild
  <scope>`, `/memory current`, `/memory help`. Every command listed in README is
  removed. `personality_edit` and the entire personality slash-command family are
  gone. Default dir is `~/assistant-memory/` (app.py:115-119), with
  `ASSISTANT_MEMORY_DIR` taking precedence over `MEMORY_DIR`.
- **Severity**: CRITICAL. A user copy-pasting from README will type commands that
  silently fall through to the LLM (since the new handler returns "Unknown memory
  subcommand…" only for `/memory <known-subcmd>` — `/memory projects` returns
  "Unknown memory subcommand: projects" but `/memory personality show` would
  return that too, with no hint what the new commands are).
- **Fix**: Rewrite the Persistent Memory section + the Memory commands table +
  the project-structure tree in both the English and Chinese halves of README.

### D2. README.md project-structure tree lists files that have been deleted
- **Doc**: `README.md:170-186` (English) and `README.md:397-413` (中文).
- **Claim**: Documents `src/agent/memory/` as containing `manager.py`, `store.py`,
  `models.py`, `session.py`, `digest_worker.py`, `digest.py`, `context.py`,
  `onboarding.py`, `personality.py`, `commands.py`, `llm.py`, `prompts.py`,
  `config.py`, `tokens.py`. Architecture description (README.md:213-214,
  440-441) frames Memory layer in terms of these modules.
- **Reality**: `ls src/agent/memory/` shows only `__init__.py` + `models.py` (the
  latter kept solely so the migration script can deserialize old JSON). All
  other files were deleted. The active memory subsystem is `src/agent/assistant_memory/`
  with `manager.py`, `curator.py`, `retrieval.py`, `prompts.py`, `schema.py`,
  `store.py` — never mentioned in README.
- **Severity**: CRITICAL — documentation describes a directory layout that does
  not exist on disk.
- **Fix**: Replace the `memory/` block in the tree with the real `assistant_memory/`
  layout; update the architecture paragraph.

### D3. README.md still documents `digest_worker.py` background subprocess
- **Doc**: `README.md:114-116` and `README.md:340-342`.
- **Claim**: "On exit, a **background subprocess** generates a digest of the
  conversation… so the main process exits immediately without waiting."
- **Reality**: `on_exit` (manager.py:169-192) spawns a **daemon thread**, not a
  subprocess. Behavior diverges in important ways: a daemon thread dies when the
  process exits, so a fast quit can truncate the digest before it is written
  (this is a separate threading bug, not a doc bug, but the doc lying about it
  hides the bug).
- **Severity**: CRITICAL.
- **Fix**: Update README to describe the daemon-thread "Dreaming…" model and call
  out the `consolidate_session + summarize_session` pair.

---

## HIGH (technically wrong, masks bugs / divergence)

### D4. Design doc's "log/_manifest.md monthly summary" is not what code or migration writes
- **Doc**: `assistant-memory-design.md:124-139` shows `log/_manifest.md` as a
  monthly bullet summary like `## 2026-04 (current month)\n- Mom's surgery…`.
  CLAUDE.md (lines 28, 29) inherits this framing.
- **Reality**: Migration script writes `_empty_manifest("Log")` →
  `# Log Manifest\n` (migrate_to_assistant_memory.py:88-89, 187). There is no
  code that ever produces or maintains the per-month bullet list. The curator
  has no `log/_manifest.md` updater; `consolidate_session` only manipulates
  people/preferences/projects manifests (curator.py:225). `summarize_session`
  appends to `log/YYYY-MM/YYYY-MM-DD.md` but never touches `log/_manifest.md`.
- **Severity**: HIGH — the spec promises retrievable monthly summaries that
  Stage 1 could reason over; in practice the log manifest stays empty forever,
  which is one of the reasons spec query #5 ("上个月我去了哪？") and #8 ("我去年
  这时候在做什么？") are downgraded to *scope-only* in the e2e test (see D8).
- **Fix**: Either implement an updater (curator should append to `log/_manifest.md`
  in `summarize_session`) or strike the monthly-summary contract from CLAUDE.md
  and the design doc.

### D5. Design doc says `identity/me.md` should NOT be auto-edited; consolidation forbid-list omits it
- **Doc**: `assistant-memory-design.md:155-157` and CLAUDE.md:24 — `identity/me.md`
  is "user-maintained. Don't auto-edit." `CONSOLIDATION_PROMPT` itself
  (prompts.py:154-157) tells the LLM "`identity/me.md` immutable fields … unless
  user explicitly stated a change this session."
- **Reality**: `Curator._FORBIDDEN_PATHS = ("identity/agent.md", "context/current.md")`
  (curator.py:211). The hard guard does not include `identity/me.md`. So if the
  consolidation LLM proposes a write to `identity/me.md`, the guard accepts it
  and `apply_writes` runs it as Layer 1 (silent). The only protection is the
  prompt, which is not a hard rule.
- **Severity**: HIGH — divergence between prompt-level "don't" and code-level
  "won't". A model misread of the prompt silently rewrites the user's identity
  file with no confirmation.
- **Fix**: Add `"identity/me.md"` to `_FORBIDDEN_PATHS`. If partial edits to
  `me.md` are intentionally allowed (the prompt suggests so for "new sub-bullets"),
  then either narrow that to append-only via op-level allowlist or update the
  CLAUDE.md/design wording to be honest that `me.md` *can* be auto-appended.

### D6. CLAUDE.md model names diverge from settings.py defaults
- **Doc**: CLAUDE.md:38, 39 lists Stage 1/2 model as `deepseek-v4-flash` and
  main/curator as `deepseek-v4-pro`. README.md:51 says `DEEPSEEK_MODEL` defaults
  to `deepseek-v4-pro`.
- **Reality**: `settings.py:131-133` reads `DEEPSEEK_MODEL_PRO` (default
  `deepseek-v4-pro`) and `DEEPSEEK_MODEL_FLASH` (need to confirm default;
  grep showed lines 131-132 only). README does not document the new env vars
  `DEEPSEEK_MODEL_PRO` / `DEEPSEEK_MODEL_FLASH` at all (the env table at
  README.md:46-58 is also stale).
- **Severity**: HIGH for README (env vars undocumented), MEDIUM for CLAUDE.md
  (gives correct names but readers won't know to set the new env vars).
- **Fix**: Add `DEEPSEEK_MODEL_PRO` / `DEEPSEEK_MODEL_FLASH` to README env table;
  optionally call them out in CLAUDE.md.

### D7. CLAUDE.md says `context/current.md` is "User-maintained, not LLM-edited" — partly false
- **Doc**: CLAUDE.md:27 and design doc line 38 ("not in any manifest; curator
  may edit"). The design doc itself contradicts CLAUDE.md.
- **Reality**: Code blocks `context/current.md` from consolidation writes
  (`_FORBIDDEN_PATHS`) but does NOT block the per-turn curator
  (`apply_writes` is called with no path filter — curator.py:117-143). The
  CURATOR_PROMPT (prompts.py:92-137) does not mention `context/current.md` as
  forbidden. So per-turn curator can silently write to it; consolidation cannot.
- **Severity**: HIGH — inconsistency between the two write-paths and
  inconsistency between CLAUDE.md ("not LLM-edited") and design doc ("curator
  may edit") and code (one of two curator paths can edit it).
- **Fix**: Pick one. If the policy is "curator cannot write current.md" (as
  CLAUDE.md says), apply the same `_FORBIDDEN_PATHS` filter inside
  `apply_writes`/`_apply_single`. Update prompts and design doc to match.

---

## MEDIUM

### D8. Design doc's 10 validation queries are NOT verbatim in test
- **Doc**: `assistant-memory-design.md:228-241` lists 10 queries in exact form.
- **Test**: `tests/test_assistant_memory_e2e.py:543-557` lists them in
  identical wording — strings DO match verbatim. Good.
- **But**: queries #3 ("我最近在做什么项目？"), #5, #8 are downgraded to
  `scope_only=True` (no file-level assertion). The design doc framed all 10 as
  the spec — the test silently relaxes 3/10 to scope-coverage only and gates
  the aggregate at "≥8/10 passed" (line 626). A reader of the design would
  expect 10/10 file-level. Drift is in test rigor, not query text.
- **Severity**: MEDIUM. Document the relaxation in the design doc, or tighten
  the test by adding manifest hooks (see D4 for log).
- **Fix**: Add a "Test relaxations" note to the design doc, or implement the
  log monthly-summary so queries 5/8 can assert files.

### D9. CLAUDE.md mentions `MEMORY_DIR` is no longer in the precedence path it implies
- **Doc**: CLAUDE.md:18 — "override with `ASSISTANT_MEMORY_DIR` env" (no
  mention of `MEMORY_DIR` legacy fallback).
- **Reality**: `app.py:115-119` reads `ASSISTANT_MEMORY_DIR` first, then falls
  back to `MEMORY_DIR`, then to `~/assistant-memory`. So `MEMORY_DIR` (the
  legacy var still in the README env table) silently controls the *new* memory
  dir if set. A user upgrading from the old system who still has
  `MEMORY_DIR=./agent-memory` in their `.env` will dump the new markdown tree
  into the old JSON dir.
- **Severity**: MEDIUM (footgun on upgrade).
- **Fix**: Document the fallback in CLAUDE.md. Consider warning at startup if
  `MEMORY_DIR` is set and `ASSISTANT_MEMORY_DIR` is not.

### D10. `manager.py` docstring claims "mirrors the old `agent.memory.manager.MemoryManager`"
- **Doc**: manager.py:1-5 — "AssistantMemoryManager — replaces the old
  MemoryManager facade. Public interface mirrors the old `agent.memory.manager.MemoryManager`."
- **Reality**: `src/agent/memory/manager.py` does not exist. The shim is gone.
  Calling out a class that no longer exists in the codebase is mildly
  misleading; a reader who tries to diff against the "old" interface won't find
  it. (Available in git history only.)
- **Severity**: LOW-MEDIUM. Cosmetic.
- **Fix**: Reword to "mirrors the public interface previously exposed under
  `agent.memory.manager.MemoryManager` (since deleted)."

### D11. Migration script archive default vs. doc
- **Doc**: design doc D4: "Old dir archived as `agent-memory.legacy/`."
- **Reality**: Script default is archive=True (migrate_to_assistant_memory.py:222-229)
  with `--no-archive` opt-out. `--force` overwrites a non-empty dst (line 230-232).
  The argparse description (line 215) says "Migrate old JSON memory to new
  markdown assistant memory." — terse but truthful. Help text matches behavior.
  No drift.
- **Severity**: NONE. Listed for completeness because the prompt asked.

### D12. Tool tier classification — clean
- **Reality**: `src/agent/permissions/gates.py` is solely about delete-path
  permission; it never knew about `personality_edit` (the old tool was registered
  and tier-classified elsewhere — now removed). Grep for `personality_edit`
  across the entire repo finds matches only in:
  `CLAUDE.md`, `src/SELF-CHANGELOG.md`, `tests/test_assistant_memory_migrate.py`
  (writes a fixture `personality.json` for the migration test),
  `scripts/migrate_to_assistant_memory.py` (reads the old `personality.json`),
  `.planning/assistant-memory-design.md`. **No leftover registration in
  `tools/registry.py`** — verified by reading the full file. Permissions module
  is clean. No drift.
- **Severity**: NONE.

### D13. Slash commands — all four are wired, but…
- **Reality**: `/memory list`, `/memory show`, `/memory rebuild`, `/memory current`,
  `/memory help` are all dispatched in `handle_command` (manager.py:307-337).
  All work. Note: `/memory current` returns the **body** of `context/current.md`
  but discards frontmatter (line 335-336 calls `read_current_context` which
  strips meta). Probably intended; just flagging.
- **Severity**: NONE.

---

## LOW

### D14. README mentions `agent-memory/` as a current directory
- **Doc**: README.md:106-107, 333. Same family as D1/D2; covered there.

### D15. CLAUDE.md "src/agent/memory/ — legacy: only models.py kept" — TRUE
- **Reality**: `ls src/agent/memory/` → `__init__.py` + `models.py` only. The
  claim holds. (`__init__.py` is empty, so "only models.py" is colloquially
  correct.) No drift.

### D16. SELF-CHANGELOG.md references `personality.json` historically
- **Doc**: `src/SELF-CHANGELOG.md` mentions `personality.json` ~10 times across
  historical entries.
- **Reality**: It is a changelog of past edits made to the deleted file. Not
  drift — it's an archive.
- **Severity**: NONE. (Flagged because the prompt asked to grep.)

---

## Test coverage gaps (called out by the prompt)

### G1. `on_exit` test only checks the return string, not that **both** consolidate
   and summarize ran
- File: `tests/test_assistant_memory_manager.py:141-150`. The test mocks
  `summarize_session` and never asserts it was called; never mocks/asserts
  `consolidate_session`. The thread is daemon and racy — even if the test
  joined, it might not have run.
- Fix: Either join the thread inside `on_exit` (would need code change) or
  patch `threading.Thread` to capture and execute the target synchronously,
  then assert both `consolidate_session` and `summarize_session` were called.

### G2. No test for `-memlog` / `--memlog` CLI flag
- File: `app.py:75-99`. `_enable_memlog` adds a logging handler that turns
  `agent.assistant_memory` INFO logs into orange MEMORY panels. Zero tests for
  the parsing, handler attachment, panel rendering, or that propagation is set
  to False (which it is — line 91; an undocumented behavior change).
- Fix: Add a unit test that calls `_enable_memlog`, emits a log on
  `agent.assistant_memory`, and asserts `print_mem_event` was called.

### G3. No test for `print_mem_event` panel rendering
- File: `display.py:217-227`. New display function, no test.
- Fix: Snapshot test against captured Console output (or assert it doesn't
  raise for a representative message).

### G4. No test for the daemon-thread curator firing after `on_assistant_turn`
- File: `manager.py:159-167`. The threading dispatch is invisible from
  `test_assistant_memory_manager.py`'s mock-based tests; tests stub
  `propose_writes` so the thread never does work. No test verifies the thread
  is daemon (would survive REPL crash) or that `apply_writes` actually runs.
- Fix: Patch `threading.Thread` to run the target synchronously and assert the
  pipeline `propose_writes → apply_writes → apply_manifest_updates` executes
  in order.

### G5. No test for `_resolve_project` flows
- File: `app.py:22-72`. Only manual interaction; no test covers the
  `new`/`existing`/`skip` branches or the project-listing display.
- Fix: Optional. Cli flow is hard to test; can wait.

### G6. No test verifies that `current.md` is included in every retrieval
- The design says "Stage 1 always include `context/current.md` implicitly". The
  code achieves this not via Stage 1 at all, but by `retrieval.retrieve` always
  attaching `current_context = self.store.read_current_context()` to the result
  (retrieval.py:128) and `on_startup` always attaching it to the system prompt
  (manager.py:121-122). `test_current_context_always_included` (e2e test:
  647-659) covers the on_startup path. **No test covers the `retrieve()`
  output**. Minor gap.
- Fix: Add an assertion in retrieval tests that `result["current_context"]` is
  always populated regardless of which scopes Stage 1 returned (including the
  fallback case).

---

## Summary

The two big offenders:
1. **README.md** is a full version behind — three top sections (memory layout,
   commands, project tree) describe a system that was deleted.
2. **`identity/me.md` and `context/current.md` write-protection** is inconsistent
   between prompt text, `_FORBIDDEN_PATHS`, and the two curator paths
   (per-turn vs. consolidation). One write path can clobber files the design
   says are off-limits.

Most other items are small (stale docstring, missing env-var documentation,
test relaxations not noted in the design doc). The migration script, slash
command wiring, permission tier system, and personality_edit removal are all
clean — no leftovers in registry, permissions, or runtime code.

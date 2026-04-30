# Adversarial Review 03 — Schema, Frontmatter, Manifest Integrity

Scope: `src/agent/assistant_memory/{schema,store,curator}.py`, `scripts/migrate_to_assistant_memory.py`, `src/agent/assistant_memory/manager.py`.

---

## F1. `parse_frontmatter` mistakes a body `---` for the closing fence

- **Location**: `schema.py:16-19, 28-44`
- **Property at risk**: lossless frontmatter round-trip; body integrity.
- **Scenario**: regex `\A---\s*\n(?P<meta>.*?)\n---\s*\n?(?P<body>.*)\Z` is non-greedy on the meta block. The first `---` *line* anywhere in the file terminates frontmatter. So a file that legitimately starts with `---\n` but has *no* YAML closer (e.g. a hand-edited markdown horizontal rule on line 5 used as a section divider) will swallow lines 2-4 as YAML and lines 5+ as the body. Worse, multi-line YAML strings that themselves contain a literal `---\n` (e.g. `immutable_core: |` block whose content includes `---`) get truncated: the regex stops at the first `---` line and YAML loads only the prefix.
- **Severity**: high. Direct violation of D2 — `immutable_core` is a multi-line block string that users will paste agent-soul material into.
- **Fix sketch**: hand-roll the parser: require the file to start with a line `^---$`, then scan line-by-line for the *next* line whose stripped value is exactly `---`; YAML-load everything between. Reject (return `{}, text`) only if no closer found.

## F2. `parse_frontmatter` silently drops malformed YAML

- **Location**: `schema.py:41-44`
- **Property**: data preservation; user signal of corruption.
- **Scenario**: `yaml.safe_load` raises `YAMLError` on malformed YAML (tabs, unbalanced quotes, etc.). Currently uncaught — propagates up and crashes `read_file`, which is called from `_apply_single("append")`, `read_immutable_core`, `on_startup`, etc. A single hand-edit typo bricks startup. Conversely the code branch `if not isinstance(loaded, dict): loaded = {}` *silently* discards a top-level scalar/list, so `--- \nfoo\n---` parses as `({}, body)` and a later write clobbers the user's intent.
- **Severity**: medium-high. Crash-on-startup vs. silent data loss — pick your poison.
- **Fix**: try/except around `safe_load`, log+return `({}, text)` so caller can decide. Surface a curator warning rather than overwriting.

## F3. `dump_frontmatter` is not byte-for-byte stable for hand-edited files

- **Location**: `schema.py:47-54`
- **Property**: round-trip stability; no curator-induced churn.
- **Scenario**: `yaml.safe_dump(..., sort_keys=False)` preserves *insertion* order, but it does *not* preserve: original quoting style (`'foo'` vs `foo`), flow style (`tags: [a,b]` vs block list), comments, blank lines, or original indentation. Every `update_field` call rewrites the entire frontmatter block. So a user who hand-formats `agent.md` with `immutable_core: |` block scalar plus comments will see comments stripped and quoting normalized on the next curator write. Diff churn = noise; multi-line `immutable_core` may switch from `|` literal to `"...\n..."` flow scalar depending on YAML emitter heuristics, breaking visual review.
- **Severity**: medium. Silent reformatting is inevitable with PyYAML; the bigger risk is that round-trip is *non-idempotent* — `parse → dump → parse → dump` may stabilize on iteration 2, but iteration 1 looks like vandalism in git.
- **Fix**: use `ruamel.yaml` round-trip mode for files curator may touch, OR document that the curator owns the frontmatter format.

## F4. `_apply_single("append")` strips trailing newline + collapses whitespace

- **Location**: `curator.py:152-156`
- **Property**: body fidelity.
- **Scenario**: `body.rstrip() + "\n\n" + content.strip() + "\n"`. If body ended with a meaningful blank line inside a fenced code block (` ```\n\n``` `), `rstrip()` kills it. If `content` itself contains intentional leading/trailing blank lines, `strip()` kills those too. Append into a fenced code block at end of file produces malformed markdown.
- **Severity**: low-medium. Cosmetic for prose, real for code-bearing notes.

## F5. `_apply_single("append")` — no frontmatter case

- **Location**: `curator.py:152-156` + `store.write_file` `:37-39`
- **Property**: schema invariant ("every file except `_index.md` and manifests has frontmatter", per design.md:47).
- **Scenario**: file with no frontmatter (e.g. user hand-created `people/alex.md` as plain markdown) is read as `({}, full_text)`. `write_file` calls `dump_frontmatter({}, body)` which, per `schema.py:49-50`, returns `body` *without* adding a frontmatter block. So the file remains frontmatter-less and Stage 2 retrieval has no structured hooks. Worse, manifests assume each file has metadata — a frontmatter-less file silently drops out of any meta-driven recall.
- **Severity**: medium. Schema invariant is observable, not enforced. Curator should refuse-or-stub frontmatter on append to a meta-less file.

## F6. `update_field` on missing file silently creates a frontmatter-only file

- **Location**: `curator.py:167-176`
- **Property**: caller-observable error vs. silent creation.
- **Scenario**: `read_file` on missing path returns `({}, "")`. Code does `meta = {field: value}` and writes. Result: a new file is created at any path the LLM hallucinates (e.g. `update_field` with `file: "peeple/alex.md"` typo writes a fresh file in a non-canonical scope dir; or `file: "../etc/passwd"` — there's no path validation in the store either, see F12). LLM proposing `update_field` is meant for known files; should error on missing.
- **Severity**: high (typo silently forks the store; path traversal possible).
- **Fix**: explicit `path.exists()` check, return None on miss; reject `..` in `rel_path` in `_abs`.

## F7. `update_field` type coercion / round-trip instability

- **Location**: `curator.py:167-176`
- **Property**: type stability across writes.
- **Scenario**: LLM emits `{"field":"tags","value":"python, agents"}` (string) vs. `["python","agents"]` (list). Whatever it provides is dumped verbatim. A subsequent retrieval prompt that reads `tags: python, agents` won't parse as a list. Similarly `{"field":"since","value":2024}` (int) vs `"2024"` (str) is non-deterministic. There is no schema enforcement on per-scope frontmatter (no `ProjectFile.validate(meta)` call anywhere — the dataclasses in `schema.py` exist but are never instantiated against on-disk meta).
- **Severity**: medium. Quality of retrieval signal degrades over time as types drift.

## F8. Manifest line substring match — `**alex.md**` vs `**alex.md.bak**`

- **Location**: `curator.py:196-200`
- **Property**: line uniqueness; correct substitution.
- **Scenario**: `if line_key in line` is a substring test. Caller passes `line_key="**alex.md**"`. Lines containing both `**alex.md**` and a separate descriptive sentence like "see also **alex.md.bak**" — the latter does *not* match (the `**` end-bold is the safety). But if the line_key is just `alex.md` (LLM omits bold markers), it matches `alexandra.md`, `**alex.md.bak**`, and any URL. The contract is implicit; nothing enforces that `line_key` be the bolded filename token. Also: `replace_all=False` only replaces the *first* match, so a manifest that accidentally has duplicate lines for the same file gets only one updated → divergence.
- **Severity**: medium. Add a strict matcher: anchor on `- **<file>**` at line start.

## F9. Manifest format drift — no schema validation on `new_line`

- **Location**: `curator.py:183-207`; rebuild at `:365-412`
- **Property**: Stage 2 retrieval parsability.
- **Scenario**: per-turn curator LLM emits arbitrary `new_line` strings. Nothing checks they begin with `- **<file>.md**` or use pipe delimiters. Over many turns, manifests drift into prose. Stage 2 prompts that show a manifest to flash-tier LLMs depend on the pipe-delimited hook format; drift quietly degrades recall. The `rebuild_manifest` function exists but is never automatically invoked.
- **Severity**: medium-high (degrades the very retrieval the system relies on).
- **Fix**: validate `new_line` regex `^- \*\*[^*]+\.md\*\* \| ` before applying; on miss, log + drop or trigger rebuild.

## F10. Manifest "append if not found" creates orphan/duplicate lines

- **Location**: `curator.py:201-203`
- **Property**: one-line-per-file invariant.
- **Scenario**: LLM emits a `manifest_update` for `line_key="**bob.md**"` that doesn't yet exist; code appends `new_line`. Next turn LLM repeats with a slightly different `line_key` (`"bob.md"` no bold) — substring miss, *another* line appended. Manifests grow duplicates. No dedup.

## F11. `list_files` does not exclude `_index.md`, hidden files, `.tmp`, or symlink loops

- **Location**: `store.py:55-64`
- **Property**: scope listing hygiene.
- **Scenarios**:
  - `_index.md` lives at root, but if `scope == ""` (or someone passes the root by mistake) `rglob("*.md")` picks it up. Currently `list_files` is only called per-scope so this is latent, not active.
  - `.DS_Store`, `.gitkeep` — only `.md` is matched, so safe by extension. But `_manifest.md` *inside subdirs* (e.g. `log/2026-04/_manifest.md` if curator decides to add one) is not filtered: only the literal `path.name == "_manifest.md"` check filters at any depth, so that case is actually OK.
  - `.tmp` leftovers: `_atomic_write` (`store.py:25-29`) creates `path.with_suffix(path.suffix + ".tmp")` → `alex.md.tmp`. If interrupted between `write_text` and `os.replace`, a stale `alex.md.tmp` survives. `rglob("*.md")` will *not* match `.md.tmp` (good), so retrieval is safe — but `parse_frontmatter` is never called on it, and disk fills.
  - `log/YYYY-MM/YYYY-MM-DD.md` recurses correctly (rglob), good — but the returned rel path is `log/2026-04/2026-04-29.md`, fine.
  - Symlink to a parent directory under a scope → infinite recursion in `rglob`. No `follow_symlinks=False` guard.
- **Severity**: low-medium. Tmp leftovers + symlink recursion both possible.

## F12. No path traversal protection in `_abs`

- **Location**: `store.py:22-23`
- **Property**: confinement to memory root.
- **Scenario**: `read_file("../../etc/passwd")` resolves to the literal join. Curator LLM is the input source; an injected user message ("when you write memory, set `file` to `../../...`") could escape. Also `rel.startswith(fp)` check in `consolidate_session` (`curator.py:257`) compares against `"identity/agent.md"` but a value `"../identity/agent.md"` doesn't start with that prefix and bypasses the forbidden-paths gate while still resolving inside `identity/` after `os.replace`.
- **Severity**: high. LLM-controlled path with no normalization.
- **Fix**: `(self.root / rel).resolve()`, then assert `self.root.resolve()` is a parent.

## F13. `consolidate_session` forbidden-path check uses `startswith`, not equality on resolved path

- **Location**: `curator.py:255-258`
- **Property**: protect immutable identity + ephemeral context.
- **Scenario**: `rel.startswith("identity/agent.md")` matches `identity/agent.md` and `identity/agent.md.bak`. Lower-impact, but `rel == "identity/agent.md/whatever"` shouldn't even be reachable. Bigger concern: case sensitivity (`Identity/agent.md` on macOS HFS+/APFS case-insensitive volumes resolves to the same file) bypasses the check.
- **Severity**: medium on case-insensitive FS.

## F14. Migration: `last_summarized_session: ''` vs design's `str | None`

- **Location**: `migrate_to_assistant_memory.py:60`; `schema.py:71`
- **Property**: type consistency.
- **Scenario**: `_project_meta` writes `"last_summarized_session": p.last_summarized_session or ""`. So a project that never had a digest gets the empty string. Curator's `summarize_session` (`curator.py:319`) writes `pmeta["last_summarized_session"] = date` (a real date). Anyone querying "is this `None` / empty?" must handle both `""` and absence. The dataclass default is also `""` (`schema.py:71`). At least it's consistent — but YAML emits `last_summarized_session: ''` which round-trips through `safe_load` as the empty string `""`. OK, but the fact that the design doc treats this as `str | None` while implementation uses `""` should be reconciled.
- **Severity**: low. Style/contract drift.

## F15. Migration: digests order on same day is `sort by timestamp` then `setdefault`

- **Location**: `migrate_to_assistant_memory.py:159-165`
- **Property**: deterministic log ordering.
- **Scenario**: digests sorted by `d.timestamp` (good), then bucketed. But `_bucket_date` does `datetime.fromisoformat(...replace("Z","+00:00"))` — if any digest has a non-ISO timestamp this raises and aborts the whole migration mid-way (after partial writes, since archive/rename happens last but project files were already written). No try/except on the parse.
- **Severity**: medium. Partial-state failure.

## F16. Migration: header-clobber on existing log file

- **Location**: `migrate_to_assistant_memory.py:168-172`
- **Scenario**: `existing_body = store.read_file(rel)` (returns "") for fresh dst, fine. But on `--force` re-run, `existing_body` is the prior migrated content. Code does `header = existing_body if existing_body else f"# {stem}\n\n"` — so on re-run, the *entire previous body* becomes the "header", then sections are re-appended. Each `--force` invocation doubles the file.
- **Severity**: medium (idempotency violation on re-runs).

## F17. Migration: writes `identity/agent.md` immutable_core as YAML scalar — quoting risk

- **Location**: `migrate_to_assistant_memory.py:131-136`
- **Property**: byte-for-byte preservation of immutable_core.
- **Scenario**: `Personality.immutable_core` is a free-form string. Passed directly into the meta dict, then `yaml.safe_dump` decides the quoting style. Multi-line strings with embedded `:` or `---` get block-scalar (`|`) treatment; ones with weird control chars become double-quoted with escape sequences. Subsequent `parse_frontmatter` round-trip *should* recover the original text but only if YAML escape rules don't lose anything (carriage returns can collapse, trailing whitespace on `|` block scalars is stripped). Not byte-stable for adversarial content.
- **Severity**: low-medium. Real personality.json content is unlikely to hit this, but it's a footgun for D2.

## F18. `read_immutable_core` silently drops non-string types

- **Location**: `store.py:70-73`
- **Scenario**: if user hand-edits `immutable_core` as a YAML list (`immutable_core: [...]`) or accidentally as an int, `read_immutable_core` returns `""` with no warning. The agent then operates without its hard-coded values — silent identity loss.
- **Severity**: medium for D2. Should at least log a warning.

## F19. `onboard` slug collision uses timestamp suffix — race / non-determinism

- **Location**: `manager.py:239-244`
- **Scenario**: if `projects/<slug>.md` exists, append `-{int(time.time())}`. Two `onboard` calls in the same second collide identically. Description like "?? !! ??" slugs to empty → fallback `f"project-{int(time.time())}"`, also collision-prone.
- **Severity**: low. Use uuid suffix or counter.

## F20. `onboard` doesn't path-validate slug

- **Location**: `manager.py:50-55`
- **Scenario**: regex strips non-alnum to `-`, so safe from `..` / `/`. But empty slug fallback `"project-<ts>"` is fine. Unicode descriptions (Chinese, emoji) all collapse to empty → all become `project-<ts>`. Multiple Chinese-named projects collide, and the slug carries no semantic info.
- **Severity**: low. Consider transliteration (pinyin) or accepting unicode in slugs.

## F21. `_atomic_write` tmp file is *not* cleaned up on exception

- **Location**: `store.py:25-29`
- **Scenario**: `tmp.write_text` succeeds (disk full handled), `os.replace` fails (cross-device, permissions). Tmp survives forever. No `try/finally tmp.unlink(missing_ok=True)`.
- **Severity**: low. Disk hygiene only — `list_files` skips them (F11).

## F22. `apply_writes` for "create" — frontmatter detection is fragile

- **Location**: `curator.py:158-164`
- **Scenario**: `parse_frontmatter(content)` on full content; if it parses meta, the inner `meta` dict from frontmatter wins, ignoring `write["meta"]`. If it *doesn't* parse meta (no `---` prefix), code falls back to `write["meta"]` and uses the raw content as body. But: a content blob that *starts* with `---` for an unrelated reason (markdown horizontal rule literally as line 1) parses as `({}, body_after_first_---)` — then `if not meta` is True, so `write["meta"]` wins and `body = content`, which now contains the leading `---\n`. Result: file has a leading `---` followed by frontmatter dump that *also* has its own `---`. Output is malformed YAML on next read.
- **Severity**: medium.

## F23. Empty-file consumer audit — `read_immutable_core`/`read_agent_soul` on missing `identity/agent.md`

- **Location**: `manager.py:104-118`
- **Scenario**: both return empty strings → `parts` list is empty → `on_startup` returns "" (or whatever the trailing concat does). The system prompt then has *no* identity injection. Silent. The CLI startup display layer should at least warn on missing `identity/agent.md` because D2 says it's "always appended."
- **Severity**: low (degrades gracefully) but violates D2 explicitly.

---

## Severity rollup

- **High**: F1 (multi-line `---` parsing), F6 (`update_field` silent create + traversal), F12 (path traversal).
- **Medium-high**: F9 (manifest drift), F2 (malformed YAML).
- **Medium**: F3, F5, F7, F8, F10, F11 (subset), F13, F15, F16, F17, F18, F22.
- **Low**: F4, F14, F19, F20, F21, F23.

## Top-three recommended next steps

1. Replace the regex frontmatter parser with a line-aware one (F1) and harden `_abs` against traversal (F12) — both are simple and close real LLM-driven bugs.
2. Make `update_field` reject missing files (F6); add a `validate_meta` per-scope hook (F7, F18).
3. Add a `_validate_manifest_line` regex gate before `apply_manifest_updates` writes anything (F9, F10) — the cheapest insurance against manifest decay.

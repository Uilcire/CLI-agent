# Assistant-Memory Robustness Report

Owner: `adversary-robustness`. Companion to `adversary-injection`.

Suite: `tests/adversarial/test_robustness.py` (Phase 1) + `tests/adversarial/test_robust_post_merge.py` (Phase 2). Run from repo root with `uv run pytest tests/adversarial/test_robust*.py -s`.

Repo HEAD at the time of this report: `59a520f`.

## Pass matrix

| Area | Tests | Pass | Skip | Fail |
|---|---:|---:|---:|---:|
| A. Pathological inputs (empty / 1MB / unicode / RTL / ZWJ) | 11 | 11 | 0 | 0 |
| B. Frontmatter (no FM, empty FM, anchors, block-scalar, malformed) | 7 | 7 | 0 | 0 |
| C. Two-layer pages (split / join / huge timeline / unicode / multi-sep) | 11 | 11 | 0 | 0 |
| D. Tier escalation (corruption, overflow, case, 20+50 threads) | 9 | 9 | 0 | 0 |
| E. Signal detector (empty, non-JSON, hang timeout, 100-thread storm) | 9 | 9 | 0 | 0 |
| F. Retrieval (empty index, huge manifest, hints: 0/1/100/unicode/long/non-str) | 8 | 8 | 0 | 0 |
| G. Filesystem (disk full, symlink, case-collision, read-only) | 4 | 4 | 0 | 0 |
| H. Migration script (idempotent ×3, empty, 200 files, non-utf8) | 5 | 5 | 0 | 0 |
| I. Templates (`{evil}`, None, unicode, missing fields, all four templates) | 8 | 8 | 0 | 0 |
| J. Memory-note marker robustness | 4 | 4 | 0 | 0 |
| K. Performance benchmarks | 5 | 5 | 0 | 0 |
| L. Misc post-merge | 5 | 5 | 0 | 0 |
| **Total** | **86** | **86** | **0** | **0** |

## Performance benchmarks

Mac (Darwin 24.6.0, Apple Silicon, Python 3.12.13). 50–100 samples each; LLM clients are mocked so numbers reflect parse + thread + filesystem overhead only.

| Operation | Input size | p50 | p99 | Bound |
|---|---|---:|---:|---:|
| `page.split_layers` | 100k-line body | 0.4 ms | 1.0 ms | <500 ms |
| `page.append_timeline` | 100k-line body | 2.3 ms | 5.7 ms | <1 s |
| `signal_detector.detect` (mocked LLM) | typical msg | 0.04 ms | 0.15 ms | <1 s |
| `manager.retrieve_for_query` | 1000-file memory dir | 0.9 ms | 4.9 ms | <5 s |
| `manager.on_assistant_turn` (incl. curator daemon join) | 100-line user msg | 0.15 ms | 0.26 ms | <5 s |

All comfortably under bounds. Curator turn cost is <1 ms because the mocked LLM call is essentially free; in production the LLM round-trip will dominate.

## HIGH / CRITICAL findings

### HIGH-1 — `migrate_personal_scopes.py` crashes on non-utf8 bytes
- **Where:** `scripts/migrate_personal_scopes.py:55`
- **Reproducer:** `tests/adversarial/test_robustness.py::TestRobustMigration::test_robust_migrate_non_utf8_file`
- **Root cause:** `read_text(encoding="utf-8")` is wrapped in `try/except OSError`, but `UnicodeDecodeError` is a `ValueError`, not an `OSError`. A single corrupt byte halts the migration entirely; `projects.legacy/` is never created and partial state remains.
- **Recommendation:** widen the except to `(OSError, UnicodeDecodeError)`, or read with `errors="replace"`.

### HIGH-2 — `people/_manifest.md` clobber → silent data loss
- **Where:** `store.list_files` (which filters `_manifest.md`) + `tiers.record_mention` (no slug normalization).
- **Reproducer:** `test_robustness.py::TestRobustPathologicalInputs::test_robust_pathological_name_clashes_with_manifest`
- **Root cause:** if a curator's slug normalizer ever produces `"_manifest"` or `"_index"`, the resulting file collides with `people/_manifest.md`. The store happily writes it and `list_files` then hides it (filters by name == `_manifest.md`). Mentions vanish from manifests.
- **Recommendation:** reject reserved slugs at write time. Add a `_RESERVED_SLUGS = {"_manifest", "_index"}` guard inside `record_mention` and any other slug-keyed write site.

## MEDIUM findings

### MEDIUM-1 — no manifest-size guard in retrieval Stage 2
- **Where:** `retrieval.py::select_files`. `read_manifest(scope)` is concatenated verbatim into the prompt.
- **Reproducer:** `test_robustness.py::TestRobustRetrieval::test_robust_retrieval_huge_manifest_size_warning`
- **Risk:** a 10 MB manifest would blow past the LLM context window before any error.
- **Recommendation:** truncate manifest to N lines or M characters before composing the Stage 2 prompt.

### MEDIUM-2 — hallucinated scope names accepted silently
- **Where:** `retrieval.py::select_files` iterates whatever `scopes` Stage 1 returned, without intersecting against `SCOPES`.
- **Reproducer:** `test_robustness.py::TestRobustRetrieval::test_robust_retrieval_unknown_scope_dropped_silently`
- **Recommendation:** `scopes = [s for s in stage1.scopes if s in SCOPES]` before Stage 2.

### MEDIUM-3 — case-insensitive FS collision on people slugs
- **Where:** `tiers.record_mention(slug)` — no slug case normalization.
- **Reproducer:** `test_robustness.py::TestRobustFilesystem::test_robust_fs_case_collision_macos`
- **Risk:** on macOS default APFS, `Alice.md` and `alice.md` resolve to the same file. The curator could shard a single person across two slugs and lose half the mentions.
- **Recommendation:** lowercase slugs at the entry point of `record_mention` and the curator's slug normalizer.

## Verified solid (kept passing under stress)

- `_safe_rel` correctly rejects `..`, NUL bytes, absolute paths, drive letters, and symlinks pointing outside root (verified via `resolve()` + `relative_to`).
- `_atomic_write` survives a simulated `OSError` from `os.replace` — the original file on disk is **byte-identical** to its pre-write content (no half-written state).
- `compute_tier` normalizes negative counts, 2³¹ overflow, and case (`"MOM"`/`"Mom"`/`"  mom  "` all → tier 1).
- `record_mention` is **correct under 50 concurrent threads** (RLock holds; `mention_count == 50` exactly, no lost increments).
- 20 distinct slugs × 5 increments × concurrent threads — no deadlock, no errors.
- `signal_detector.detect` handles empty / whitespace input (skips LLM), non-JSON / non-dict JSON / `{}` / valid JSON with garbage entities — always returns shape-stable empty signals.
- LLM hang case respects the 10 s timeout and returns empty signals; verified at 0.5 s timeout.
- 100-thread signal-detector storm: all 100 LLM calls fire, ≤2 threads above baseline after `gc.collect()`, no FD leak (within 50 fds across 200 calls).
- Retrieval `hints` parameter accepts: `[]`, `["alice"]`, 100 hints, unicode/emoji, `{evil}` (no `str.format` recursion), 10 000-char strings, mixed types (non-strings filtered).
- `render_template` does NOT recurse into placeholder values — `{evil}` lands as literal text. None coerced to "". Unknown kwargs ignored.
- `migrate_personal_scopes.py` is idempotent across **3 consecutive runs**; `projects.legacy/` is the source of truth and the archive file content does not duplicate.
- Frontmatter parser handles 10 000 keys in <5 s; YAML anchors resolve normally; recursive anchors do not hang; `|`-block scalars containing `---` lines do not split prematurely.

## Regression risks to watch

1. **Slug normalization drift.** If a future change slugs unicode names through some path that bypasses lowercase + reserved-slug checks, MEDIUM-3 / HIGH-2 reopen.
2. **Read-modify-write race in `record_mention`.** Currently safe because the store's RLock is held across `read_file → meta-mutate → write_file`. If anyone refactors `record_mention` to release the lock between read and write, lost increments return.
3. **Stage 1 hallucination contract.** Stage 1's prompt currently asks for scope names but does not constrain to the `SCOPES` enum — model drift could start producing freeform strings; MEDIUM-2 is the safety net.
4. **`split_layers` greediness.** When a body contains two canonical separators, `split_layers` takes the first; the second `---` ends up *inside* the timeline section. This is fine for normal data but can corrupt round-trips if a reader assumes "the file has exactly one separator".
5. **Migration script & `errors="replace"`.** Fixing HIGH-1 with `errors="replace"` masks data loss silently; widening `except` is the conservative choice.

## Recommended fixes (priority order)

1. (HIGH-1) Catch `UnicodeDecodeError` in `migrate_personal_scopes.py:55-58`. ~3 LoC.
2. (HIGH-2) Add a `_RESERVED_SLUGS` set + guard inside `tiers.record_mention` and the curator's slug normalizer. ~5 LoC.
3. (MEDIUM-2) Filter Stage 1 scopes against `SCOPES` in `retrieval.select_files`. ~1 LoC.
4. (MEDIUM-3) Lowercase slugs at entry of `record_mention`. ~1 LoC.
5. (MEDIUM-1) Add a manifest size guard in Stage 2 prompt composition (truncate or skip). ~5 LoC.

## How to run

```bash
uv run pytest tests/adversarial/test_robust*.py -s   # both files, with bench output
uv run pytest tests/adversarial/test_robustness.py   # Phase 1 catalog only
uv run pytest tests/adversarial/test_robust_post_merge.py -s  # Phase 2 + benchmarks
```

All 86 robustness tests pass against repo HEAD `59a520f`. The single failure observed in `tests/adversarial/test_post_merge.py::TestTemplates::test_attribute_format_string_no_attribute_access` belongs to the `adversary-injection` teammate's suite, not this one.

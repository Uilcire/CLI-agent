# Threading & Concurrency Findings

Scope: `src/agent/assistant_memory/{manager,curator,store}.py` and `src/agent/cli/app.py`.

Top-level facts that anchor the analysis:
- `AssistantMemoryStore._atomic_write` (store.py:25-29) writes a `<file>.tmp` then `os.replace` to final. No locking, no fsync.
- `AssistantMemoryManager.on_assistant_turn` (manager.py:138-167) spawns a daemon thread per assistant reply that runs `curator.propose_writes` -> `apply_writes` -> `apply_manifest_updates`.
- `AssistantMemoryManager.on_exit` (manager.py:169-189) spawns *another* daemon thread that runs `consolidate_session` then `summarize_session`.
- There is **no lock anywhere** in `assistant_memory/` (grep for `Lock|RLock` returned only the two `threading.Thread` callsites).
- `app.py` `_sigint_handler` (lines 188-193) calls `os._exit(130)` on second ^C, bypassing finally and killing daemon threads abruptly.

---

## CRITICAL (data loss / corruption)

### C1. Lost-update race on `apply_manifest_updates` and `_apply_single` "append"
- File: `curator.py:183-207` (manifest read-modify-write); `curator.py:152-156` (file append read-modify-write).
- Scenario: User sends turn N. Daemon thread A starts, fetches `current = self.store.read_manifest("people")`. Network roundtrip to deepseek for turn N+1 finishes faster than turn N's curator (or, more realistically, the user types fast and turn N+1's curator overlaps turn N's). Daemon B reads the same manifest, both compute their edits in-memory, both call `write_manifest("people", new_content)`. The second `os.replace` clobbers the first. The `[memory note: ...]` from turn N is silently lost.
- The same pattern applies to `_apply_single` op=`"append"`: `read_file` -> mutate body -> `write_file`. Two simultaneous appends to `people/alex.md` -> last writer wins, one note vanishes.
- Severity: CRITICAL. Atomic write protects against torn files, **not** against lost updates. The whole point of curator is durability of memory; silent loss is exactly the failure mode this layer must avoid.
- Repro: in a test, monkeypatch `propose_writes` to return an "append to people/alex.md" with a deterministic unique sentinel; fire `on_assistant_turn` twice in rapid succession with a `time.sleep` injected into `_apply_single` between read and write. Inspect `people/alex.md`: typically only one sentinel survives.

### C2. Per-turn curator vs. on_exit consolidation racing on the same files
- Files: `manager.py:159-167` (per-turn thread) and `manager.py:177-188` (consolidation thread); both ultimately call `curator.apply_writes` / `apply_manifest_updates`.
- Scenario: User types final turn, then `quit`. The per-turn daemon for the final assistant reply is still mid-LLM-call. `on_exit` immediately spawns the consolidation thread. Now two threads both want to mutate `people/_manifest.md` and `people/<name>.md`. Same lost-update mechanism as C1, but worse because consolidation is supposed to be the authoritative cross-turn pass.
- Severity: CRITICAL — consolidation reads manifests (`curator.py:225-228`) **before** writing; per-turn curator may slip a write in between. Result: consolidation rewrites manifest from a stale view and clobbers the per-turn update.

---

## HIGH (race / inconsistency)

### H1. `recent_turns` snapshot is shallow, but mutation is replacement so it's safe — except for one edge
- File: `manager.py:131-167`. `recent_snapshot = list(self.recent_turns)` is a shallow copy of dicts. The dicts themselves are never mutated (only new ones appended in `on_user_turn`/`on_assistant_turn`), and slicing `self.recent_turns[-_RECENT_TURN_CAP:]` rebinds the attribute rather than mutating in place. So the daemon thread holds stable references.
- BUT: between `entry = {"role": ..., "content": content}` (line 140) and the snapshot (line 156), if the previous turn's daemon thread is still running and we read `self.recent_turns` here, we are reading from main thread only — Python's GIL serializes list ops, so this specific read is fine.
- Verdict: not a bug for state shape, but the design is fragile. If a future change adds dict-level mutation (e.g. an "edited" flag) this becomes a true race.
- Severity: HIGH because a one-line change makes it real, but no current bug.

### H2. `_active_session_messages` mutated by main thread while consolidation reads it
- File: `manager.py:173`: `messages = list(self._active_session_messages)` — shallow copy of dicts. `on_exit` is only called from the REPL `finally` block (`app.py:250`), which runs **after** the `while True` loop exits, so no further `on_user_turn`/`on_assistant_turn` can append. The list is frozen w.r.t. the main thread at exit. Confirmed safe.
- BUT: the dicts are shared with `recent_turns`, and any future code that mutates an entry (e.g. redaction) would race with the consolidation thread reading them.
- Severity: NOT-A-BUG today. Listed here because the question was raised in the brief.

### H3. Daemon thread killed mid-`os.replace` leaves `.tmp` litter
- File: `store.py:25-29`. `_atomic_write` writes `<path>.tmp` then `os.replace(tmp, path)`. If the process dies (second ^C -> `os._exit(130)`) between `tmp.write_text` and `os.replace`, the final file is untouched (good — atomicity preserved) but the `.tmp` file remains on disk.
- Over time, repeated mid-flight kills accumulate `people/_manifest.md.tmp`, `people/alex.md.tmp`, etc. They are not hidden, not in `.gitignore` for the memory dir, and `list_files` does include `.tmp` files? — actually `list_files` filters by `*.md` glob (`store.py:60`), so `.md.tmp` files are excluded. Good.
- Severity: HIGH for hygiene — these files are never cleaned up. Some users may notice them; worse, a stale `people/alex.md.tmp` from a crashed write is human-readable garbage that looks like a memory file.

### H4. Curator network call cannot be interrupted; second ^C is the only escape
- File: `curator.py:92-97`, `curator.py:233-238`, `curator.py:289-292`. The deepseek SDK call is synchronous. Daemon thread is `daemon=True` so process exit *can* kill it, but the thread is blocked on a socket; only `os._exit` (forced kill) actually frees it. `sys.exit` from the main thread would wait at interpreter shutdown for non-daemon threads only — these are daemons, so it's fine.
- The `os._exit(130)` path on double-^C (app.py:191) does kill the thread cleanly at the kernel level. The `quit`/`exit` path triggers `on_exit` which spawns the consolidation thread and then... returns. Main thread exits. Daemon dies. **The consolidation/digest writes are silently dropped if the LLM call has not yet completed.**
- Severity: HIGH. The user types `quit`, sees "Dreaming...", thinks their session was digested. In reality the digest may be aborted at interpreter teardown 200ms later. There is no `t.join(timeout=...)` and no progress signal to the user.

### H5. `apply_writes` "create" op can clobber a concurrently-created file
- File: `curator.py:158-164`. `op="create"` calls `self.store.write_file(rel, ...)` unconditionally — no existence check. If two curator threads both decide to "create" `people/jamie.md` (e.g. user mentions Jamie twice in quick succession, both turns trigger curator, neither has yet written), the second write clobbers the first. Same lost-update class as C1.
- Severity: HIGH.

---

## MEDIUM (cleanup / hygiene)

### M1. Test asserts curator was called synchronously — flaky
- File: `tests/test_assistant_memory_manager.py:73-85` (`test_on_assistant_turn_invokes_curator`). Asserts `propose_writes.assert_called_once()` immediately after `on_assistant_turn` returns. Curator now runs in a daemon thread (manager.py:167), so this assertion races the thread start. On a slow CI box or a busy interpreter, the assertion can fire before the thread schedules — false negative. On a fast box it usually wins.
- Severity: MEDIUM (flaky test, not a product bug). Fix: have the test wait on the thread, or expose a synchronous mode.
- Note: `test_on_exit_returns_background_message` (line 141) is similarly racy if it asserted on `summarize_session` calls, but it only checks the return string — safe.

### M2. No fsync in atomic write — power loss can lose recent writes
- File: `store.py:25-29`. `os.replace` is atomic w.r.t. concurrent readers but not durable across crashes. On macOS especially, the rename can be reordered with the file data flush. For a memory system this is mostly fine (next session repairs), but worth noting.
- Severity: MEDIUM-LOW.

### M3. `.tmp` files have no cleanup pass
- See H3. No startup sweep removes `*.md.tmp` from prior aborted writes.
- Severity: MEDIUM.

---

## LOW (style / hypothetical)

### L1. `Curator` shares one OpenAI client across threads
- File: `curator.py:69`. `self.client = create_client(settings)` once; both per-turn and consolidation threads call `self.client.chat.completions.create`. The OpenAI Python SDK's `Client` is documented as thread-safe (uses `httpx.Client` underneath which is thread-safe for sending). No bug, but worth noting that shared state crosses threads.
- Severity: LOW.

### L2. `self.recent_turns` reassigned on every cap (`manager.py:142`) — atomic in CPython
- `self.recent_turns = self.recent_turns[-_RECENT_TURN_CAP:]` is a single attribute store, atomic under the GIL. Safe.
- Severity: NOT-A-BUG.

---

## NOT-BUGS (investigated, ruled out)

- **`_active_session_messages` deep vs shallow copy at on_exit** — shallow, but mutation invariants of the producer (main thread, only appends; only stops at exit) make it safe today. (See H2.)
- **`recent_snapshot = list(...)` racing with main-thread append** — Python list `.append` and slicing are GIL-atomic; the snapshot is a fresh list of stable dict references. No tearing. (See H1.)
- **Daemon threads blocking process exit** — `daemon=True` is set on both threads; interpreter exit will not wait. Main concern is *lost work*, not *hung exit*. (See H4.)
- **`os._exit(130)` killing daemons cleanly** — yes; `os._exit` skips all Python cleanup including thread join. Daemons die immediately. The cost is C1/C2/H3 mid-write damage.
- **Atomic write under concurrent writers leaving torn file** — `os.replace` is atomic on POSIX and Windows; the *file content* is never half-written. The bug is *lost update*, not *corruption*.
- **Tests `test_on_user_and_assistant_turn_caps_at_six` flakiness** — uses MagicMocks for curator methods, so the daemon thread runs but does nothing observable. The assertions only inspect `recent_turns`/`_active_session_messages` which are mutated synchronously before the thread starts. Safe.

---

## Suggested fixes (per finding)

- **C1, C2, H5**: introduce a single `threading.Lock` (or per-scope lock dict) inside `AssistantMemoryStore`, and have `_atomic_write` acquire it. Even better: move every read-modify-write sequence (`apply_manifest_updates`, `_apply_single` append, `_append_manifest_line` in manager.py:261) into a `store.update_manifest_line(scope, line_key, new_line)` / `store.append_to_file(rel, content)` API that takes the lock around read+write. This eliminates the TOCTOU window.
- **C2 specifically**: in `on_exit`, before spawning the consolidation thread, `t.join(timeout=...)` the most recent per-turn curator thread. Track the last-launched thread on `self._last_curator_thread`.
- **H3, M3**: on `AssistantMemoryStore.__init__`, walk each scope dir and `unlink` any `*.md.tmp` files older than, say, 60 seconds. Cheap startup hygiene.
- **H4**: in `on_exit`, give the consolidation thread a bounded `t.join(timeout=15)` and only return "Dreaming..." once the join either completes or times out, so the user gets honest feedback. Optionally write a "session-pending.json" sentinel so the next startup can resume aborted digests.
- **H5**: `op="create"` should refuse to overwrite an existing file unless `write.get("overwrite") is True`.
- **M1**: in tests, replace `assert_called_once()` with a poll loop (`for _ in range(50): time.sleep(0.01); if mock.called: break`) or, cleaner, have the manager expose a synchronous `_run_curator_sync` test seam and patch `threading.Thread` to call `.run()` inline in unit tests.
- **M2**: optional; add `os.fsync(tmp.fileno())` and `os.fsync(parent_dir_fd)` in `_atomic_write` if durability matters. Probably overkill for personal-assistant memory.
- **L1**: no action needed; document the assumption that `create_client(...)` returns a thread-safe client.

---

## Bottom line

The two real critical issues are **C1 (lost-update on append/manifest)** and **C2 (per-turn curator racing on_exit consolidation)**. Both are concrete, reproducible, and silent — exactly the worst kind of memory bug. Everything else is either hygiene (`.tmp` litter, flaky test) or hypothetical without a code change to materialize it. The fix is small: one lock in the store + a join in `on_exit`.

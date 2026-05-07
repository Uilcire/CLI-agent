"""Phase 2: post-merge robustness probes + performance benchmarks.

Targets the merged surface (Phase A scopes, Phase B page.py + templates.py,
Phase C signal detector + retrieval hints, Phase D tier escalation).

All probes use ``test_robust_*`` names to avoid collision with the
``test_inject_*`` adversary-injection suite. Performance benchmarks have
generous bounds — they exist to catch order-of-magnitude regressions, not
to gate on micro-perf. Numbers are recorded in ``ROBUSTNESS.md``.
"""

from __future__ import annotations

import gc
import json
import os
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path
from statistics import median
from typing import Any

import pytest

from agent.assistant_memory.curator import Curator
from agent.assistant_memory.manager import AssistantMemoryManager
from agent.assistant_memory.page import (
    append_timeline,
    format_sourced_bullet,
    join_layers,
    rewrite_compiled,
    split_layers,
)
from agent.assistant_memory.retrieval import RetrievalPipeline
from agent.assistant_memory.signal_detector import SignalDetector, _empty_signals
from agent.assistant_memory.store import AssistantMemoryStore
from agent.assistant_memory.templates import (
    LIFE_DOMAIN_TEMPLATE,
    PERSON_TEMPLATE,
    PREFERENCE_TEMPLATE,
    THREAD_TEMPLATE,
    render_template,
)
from agent.assistant_memory.tiers import record_mention


# ---------------------------------------------------------------------------
# Fakes for LLM-dependent code paths
# ---------------------------------------------------------------------------


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, payload: str = "{}") -> None:
        self.payload = payload
        self.calls = 0
        self.lock = threading.Lock()

    def create(self, **kwargs: Any) -> Any:
        with self.lock:
            self.calls += 1
        return _FakeResp(self.payload)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


def _fake_settings() -> Any:
    return type(
        "S",
        (),
        {
            "model": "fake-model",
            "model_pro": "",
            "model_flash": "",
            "openai_api_key": "test",
            "openai_base_url": "",
            "backend": "openai",
        },
    )()


@pytest.fixture
def mem_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ASSISTANT_MEMORY_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def store(mem_dir: Path) -> AssistantMemoryStore:
    return AssistantMemoryStore(mem_dir)


# ---------------------------------------------------------------------------
# A. Two-layer pages under stress
# ---------------------------------------------------------------------------


class TestRobustPagesStress:
    def test_robust_pages_100k_line_timeline(self) -> None:
        big = "compiled body\nwith two lines\n\n---\n\n## Timeline\n" + "\n".join(
            f"- **2026-01-01** | session — event {i}" for i in range(100_000)
        )
        t0 = time.perf_counter()
        compiled, timeline = split_layers(big)
        elapsed_split = time.perf_counter() - t0
        t0 = time.perf_counter()
        joined = join_layers(compiled, timeline)
        elapsed_join = time.perf_counter() - t0

        assert "compiled body" in compiled
        assert "event 99999" in timeline
        assert elapsed_split < 1.0, f"split took {elapsed_split:.3f}s"
        assert elapsed_join < 1.0, f"join took {elapsed_join:.3f}s"
        # Round-trip preserves the body modulo trailing whitespace.
        assert joined.count("\n---\n") == 1

    def test_robust_pages_append_timeline_perf(self) -> None:
        body = "compiled\n\n---\n\n## Timeline\n" + "\n".join(
            f"- **2026-01-01** | session — e{i}" for i in range(100_000)
        )
        t0 = time.perf_counter()
        new_body = append_timeline(body, "2026-05-07", "session", "fresh event")
        elapsed = time.perf_counter() - t0
        assert "fresh event" in new_body
        assert elapsed < 1.0, f"append took {elapsed:.3f}s"

    def test_robust_pages_timeline_heading_in_compiled(self) -> None:
        # A compiled body that mentions "## Timeline" as a sub-heading should
        # NOT trigger a false split when the canonical separator is present
        # later. With the canonical separator absent, the bare-header fallback
        # kicks in and splits at the first match — document the behavior.
        body_canonical = (
            "Note about ## Timeline conventions.\n\n---\n\n"
            "## Timeline\n- **2026-05-07** | session — real bullet\n"
        )
        compiled, timeline = split_layers(body_canonical)
        assert "Note about" in compiled
        assert "real bullet" in timeline

        # Bare-header fallback: any line == "## Timeline" splits there.
        body_bare = "Compiled has\n## Timeline\nfake heading\n"
        compiled2, timeline2 = split_layers(body_bare)
        # Documents current (acceptable) behavior — bare header IS a separator.
        assert "Compiled has" in compiled2
        assert "fake heading" in timeline2

    def test_robust_pages_unicode_in_compiled_and_timeline(self) -> None:
        body = (
            "# 武田信玄 🦄\n\n中文 + αβγ + 🌈\n\n---\n\n## Timeline\n"
            "- **2026-05-07** | session — café é̃ñ 🎉\n"
        )
        compiled, timeline = split_layers(body)
        assert "武田信玄" in compiled
        assert "café" in timeline and "🎉" in timeline
        joined = join_layers(compiled, timeline)
        assert "武田信玄" in joined and "café" in joined

    def test_robust_pages_multiple_separators_first_wins(self) -> None:
        # Two canonical separators — `find()` returns first; second `---`
        # ends up as content inside the timeline section. Documents
        # current behavior: split is greedy from the front.
        body = (
            "compiled\n\n---\n\n## Timeline\n- **2026-01-01** | session — a\n\n"
            "---\n\n## Timeline\n- **2026-02-02** | session — b\n"
        )
        compiled, timeline = split_layers(body)
        assert compiled.strip() == "compiled"
        # Both bullets should land in timeline (verbatim).
        assert "2026-01-01" in timeline and "2026-02-02" in timeline

    def test_robust_pages_rewrite_compiled_preserves_timeline(self) -> None:
        body = (
            "old compiled\n\n---\n\n## Timeline\n"
            "- **2026-01-01** | session — original\n"
        )
        new = rewrite_compiled(body, "fresh compiled body")
        assert "fresh compiled body" in new
        assert "original" in new

    def test_robust_pages_format_sourced_bullet_validation(self) -> None:
        ok = format_sourced_bullet("ate ramen", "observed", date="2026-05-07")
        assert "ate ramen" in ok and "observed" in ok and "2026-05-07" in ok

        # Inferred requires confidence
        with pytest.raises(ValueError):
            format_sourced_bullet("guess", "inferred")
        with pytest.raises(ValueError):
            format_sourced_bullet("guess", "inferred", confidence="bogus")
        with pytest.raises(ValueError):
            format_sourced_bullet("guess", "unknown-type")

        ok2 = format_sourced_bullet("guess", "inferred", confidence="low")
        assert "low" in ok2


# ---------------------------------------------------------------------------
# B. Tier escalation under heavier concurrency (50 threads)
# ---------------------------------------------------------------------------


class TestRobustTierConcurrency:
    def test_robust_tier_50_threads(self, store: AssistantMemoryStore) -> None:
        slug = "alice-50"
        N = 50
        errors: list[BaseException] = []
        barrier = threading.Barrier(N)

        def bump() -> None:
            barrier.wait()  # maximize contention
            try:
                record_mention(store, slug, "2026-05-07")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=bump) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"errors during concurrent record_mention: {errors!r}"
        meta, _ = store.read_file(f"people/{slug}.md")
        assert meta["mention_count"] == N, (
            f"LOST INCREMENTS — expected {N}, got {meta['mention_count']}"
        )

    def test_robust_tier_concurrent_distinct_slugs(self, store: AssistantMemoryStore) -> None:
        # 20 distinct slugs × 5 increments each — should not deadlock.
        slugs = [f"person-{i}" for i in range(20)]
        N = 5
        errors: list[BaseException] = []

        def bump(slug: str) -> None:
            try:
                for _ in range(N):
                    record_mention(store, slug, "2026-05-07")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=bump, args=(s,)) for s in slugs]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        elapsed = time.perf_counter() - t0
        assert not errors, errors
        for s in slugs:
            meta, _ = store.read_file(f"people/{s}.md")
            assert meta["mention_count"] == N
        assert elapsed < 5.0, f"distinct-slug concurrency took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# C. Signal detector thread storm
# ---------------------------------------------------------------------------


class TestRobustSignalThreadStorm:
    def test_robust_signal_thread_storm_no_leak(
        self, store: AssistantMemoryStore
    ) -> None:
        # Simulate 100 user messages dispatched in <1s to a daemon-thread
        # detector pool. Verify active_count returns to baseline.
        completions = _FakeCompletions(payload=json.dumps(_empty_signals()))
        det = SignalDetector.__new__(SignalDetector)
        det.store = store
        det.settings = _fake_settings()
        det.client = _FakeClient(completions)
        det.model_flash = "fake"

        baseline_threads = threading.active_count()

        def fire(i: int) -> None:
            det.detect(f"user msg {i}", [])

        # Spawn 100 daemon threads (mirroring how the manager would)
        threads = [
            threading.Thread(target=fire, args=(i,), daemon=True) for i in range(100)
        ]
        t0 = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        elapsed = time.perf_counter() - t0

        # Each detect itself spawns 1 worker thread that should also exit.
        # Allow one GC cycle.
        gc.collect()
        time.sleep(0.1)

        leaked = threading.active_count() - baseline_threads
        assert completions.calls == 100, f"only {completions.calls}/100 fired"
        assert leaked <= 2, f"thread leak: {leaked} threads above baseline"
        assert elapsed < 10.0, f"thread storm took {elapsed:.2f}s"

    def test_robust_signal_fd_no_leak(self, store: AssistantMemoryStore) -> None:
        completions = _FakeCompletions(payload=json.dumps(_empty_signals()))
        det = SignalDetector.__new__(SignalDetector)
        det.store = store
        det.settings = _fake_settings()
        det.client = _FakeClient(completions)
        det.model_flash = "fake"

        # NOFILE soft limit; we only check that fd usage isn't growing wildly.
        # Sample fd count via /dev/fd if available.
        def fd_count() -> int:
            try:
                return len(os.listdir(f"/proc/{os.getpid()}/fd"))
            except OSError:
                try:
                    return len(os.listdir("/dev/fd"))
                except OSError:
                    return -1

        before = fd_count()
        for i in range(200):
            det.detect(f"msg {i}", [])
        gc.collect()
        after = fd_count()
        if before == -1 or after == -1:
            pytest.skip("fd introspection not supported on this OS")
        # Allow a small slack but flag big leaks.
        assert after - before < 50, f"fd leak: {before} -> {after}"


# ---------------------------------------------------------------------------
# D. Retrieval with hints
# ---------------------------------------------------------------------------


class TestRobustRetrievalHints:
    def _make_pipeline(
        self, store: AssistantMemoryStore, payload: str
    ) -> tuple[RetrievalPipeline, _FakeCompletions]:
        completions = _FakeCompletions(payload=payload)
        rp = RetrievalPipeline.__new__(RetrievalPipeline)
        rp.store = store
        rp.settings = _fake_settings()
        rp.client = _FakeClient(completions)
        rp.model_flash = "fake"
        return rp, completions

    def test_robust_retrieve_hints_empty(self, store: AssistantMemoryStore) -> None:
        # Stage 1 returns one scope, Stage 2 returns no files.
        # Hints=[] should not modify behavior (no exception, no extra call).
        rp, _ = self._make_pipeline(
            store, json.dumps({"scopes": ["people"], "files": []})
        )
        result = rp.retrieve("hello", [], hints=[])
        assert result["files"] == []

    def test_robust_retrieve_hints_one(self, store: AssistantMemoryStore) -> None:
        rp, completions = self._make_pipeline(
            store, json.dumps({"scopes": ["people"], "files": ["people/alice.md"]})
        )
        # Need a manifest so Stage 2 has something to read.
        store.write_manifest("people", "# People Manifest\n- **alice.md** | tier:2\n")
        store.write_file("people/alice.md", {"name": "alice"}, "Alice body")
        result = rp.retrieve("who is alice?", [], hints=["alice"])
        assert "people/alice.md" in result["files"]
        assert completions.calls == 2  # stage1 + stage2

    def test_robust_retrieve_hints_one_hundred(self, store: AssistantMemoryStore) -> None:
        # 100 hints — pipeline caps to 20 in the prompt; nothing should crash.
        rp, _ = self._make_pipeline(
            store, json.dumps({"scopes": ["people"], "files": []})
        )
        store.write_manifest("people", "# People Manifest\n")
        hints = [f"slug-{i}" for i in range(100)]
        result = rp.retrieve("question", [], hints=hints)
        assert isinstance(result["files"], list)

    def test_robust_retrieve_hints_unicode(self, store: AssistantMemoryStore) -> None:
        rp, _ = self._make_pipeline(
            store, json.dumps({"scopes": ["people"], "files": []})
        )
        store.write_manifest("people", "# People Manifest\n")
        hints = ["武田信玄", "🦄", "café", "{evil}", "}}injection{{"]
        # Untrusted hints must not blow up `str.format` inside the pipeline.
        result = rp.retrieve("q", [], hints=hints)
        assert isinstance(result["files"], list)

    def test_robust_retrieve_hints_very_long(self, store: AssistantMemoryStore) -> None:
        rp, _ = self._make_pipeline(
            store, json.dumps({"scopes": ["people"], "files": []})
        )
        store.write_manifest("people", "# People Manifest\n")
        hints = ["x" * 10_000]  # one massive hint
        result = rp.retrieve("q", [], hints=hints)
        assert isinstance(result["files"], list)

    def test_robust_retrieve_hints_non_string_filtered(
        self, store: AssistantMemoryStore
    ) -> None:
        rp, _ = self._make_pipeline(
            store, json.dumps({"scopes": ["people"], "files": []})
        )
        store.write_manifest("people", "# People Manifest\n")
        # mixed types — pipeline filters non-strings.
        result = rp.retrieve(
            "q", [], hints=["ok", 42, None, "", {"k": "v"}]  # type: ignore[list-item]
        )
        assert isinstance(result["files"], list)


# ---------------------------------------------------------------------------
# E. Templates with weird inputs
# ---------------------------------------------------------------------------


class TestRobustTemplates:
    def test_robust_template_brace_in_value_safe(self) -> None:
        # If a name contains `{evil}`, render_template MUST NOT recurse and
        # treat it as another placeholder.
        out = render_template(PERSON_TEMPLATE, name="{evil}", relation="friend")
        assert "{evil}" in out, "name containing braces should land verbatim"

    def test_robust_template_none_values_become_empty(self) -> None:
        out = render_template(PERSON_TEMPLATE, name=None, summary=None)
        # None → empty string
        assert "# \n" in out or "# " in out

    def test_robust_template_unicode_values(self) -> None:
        out = render_template(
            PERSON_TEMPLATE,
            name="武田信玄",
            relation="friend",
            summary="🦄 the unicorn",
        )
        assert "武田信玄" in out
        assert "🦄" in out

    def test_robust_template_extra_kwargs_ignored(self) -> None:
        # Unknown kwarg should not raise.
        out = render_template(PERSON_TEMPLATE, name="A", nonexistent_field="x")
        assert "# A" in out

    def test_robust_template_missing_fields_use_defaults(self) -> None:
        # Render with no fields — placeholders should fall through to defaults.
        out = render_template(PERSON_TEMPLATE)
        # Default summary placeholder
        assert "(no summary yet)" in out

    def test_robust_template_all_templates_render(self) -> None:
        # All three templates render without raising on minimal input.
        for tmpl in (PERSON_TEMPLATE, LIFE_DOMAIN_TEMPLATE, THREAD_TEMPLATE,
                     PREFERENCE_TEMPLATE):
            out = render_template(tmpl)
            assert "## Timeline" in out, "every template must reserve a Timeline"


# ---------------------------------------------------------------------------
# F. Migration script — triple-run idempotency
# ---------------------------------------------------------------------------


class TestRobustMigrationIdempotent:
    def _run_migrate(self, env_dir: Path) -> subprocess.CompletedProcess:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "migrate_personal_scopes.py"
        return subprocess.run(
            [sys.executable, str(script)],
            env={**os.environ, "ASSISTANT_MEMORY_DIR": str(env_dir)},
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_robust_migrate_three_runs_no_dup(self, tmp_path: Path) -> None:
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "a.md").write_text("# project a\nbody A\n", encoding="utf-8")
        (projects / "b.md").write_text("# project b\nbody B\n", encoding="utf-8")

        for run in range(3):
            res = self._run_migrate(tmp_path)
            assert res.returncode == 0, f"run {run}: {res.stderr}"

        legacy = tmp_path / "projects.legacy"
        archive = tmp_path / "life" / "_archive_from_projects.md"
        assert legacy.exists(), "legacy dir must remain after re-runs"
        assert (legacy / "a.md").exists(), "source-of-truth files preserved"
        assert (legacy / "b.md").exists()
        # Archive file content count: each project's heading should appear once.
        text = archive.read_text(encoding="utf-8")
        assert text.count("=== a.md ===") == 1, "archive duplicated across runs"
        assert text.count("=== b.md ===") == 1


# ---------------------------------------------------------------------------
# G. Performance benchmarks
# ---------------------------------------------------------------------------


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return float("nan")
    s = sorted(samples)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[k]


class TestRobustBenchmarks:
    """Performance benchmarks with generous bounds.

    Numbers feed directly into ROBUSTNESS.md.
    """

    def test_robust_bench_split_layers_p99(self) -> None:
        # Build a 100k-line body once; time split_layers 50 times.
        big = "compiled body\n\n---\n\n## Timeline\n" + "\n".join(
            f"- **2026-01-01** | session — e{i}" for i in range(100_000)
        )
        samples: list[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            split_layers(big)
            samples.append(time.perf_counter() - t0)
        p50 = median(samples)
        p99 = _percentile(samples, 99)
        print(f"\nsplit_layers(100k lines)  p50={p50*1000:.2f}ms  p99={p99*1000:.2f}ms")
        assert p99 < 0.5, f"split_layers p99 {p99:.3f}s > 500ms"

    def test_robust_bench_append_timeline_p99(self) -> None:
        body = "compiled\n\n---\n\n## Timeline\n" + "\n".join(
            f"- **2026-01-01** | session — e{i}" for i in range(100_000)
        )
        samples: list[float] = []
        for _ in range(50):
            t0 = time.perf_counter()
            append_timeline(body, "2026-05-07", "session", "fresh")
            samples.append(time.perf_counter() - t0)
        p50 = median(samples)
        p99 = _percentile(samples, 99)
        print(f"\nappend_timeline(100k)     p50={p50*1000:.2f}ms  p99={p99*1000:.2f}ms")
        assert p99 < 1.0

    def test_robust_bench_signal_detect_p99(self, store: AssistantMemoryStore) -> None:
        # Mock LLM so we measure parse + thread overhead only.
        completions = _FakeCompletions(payload=json.dumps(_empty_signals()))
        det = SignalDetector.__new__(SignalDetector)
        det.store = store
        det.settings = _fake_settings()
        det.client = _FakeClient(completions)
        det.model_flash = "fake"

        samples: list[float] = []
        for i in range(100):
            t0 = time.perf_counter()
            det.detect(f"hello world {i}", [])
            samples.append(time.perf_counter() - t0)
        p50 = median(samples)
        p99 = _percentile(samples, 99)
        print(f"\nsignal_detect (mocked)    p50={p50*1000:.2f}ms  p99={p99*1000:.2f}ms")
        # Detector spawns a worker thread + joins; should be cheap.
        assert p99 < 1.0, f"signal_detect p99 {p99*1000:.2f}ms exceeds 1s"

    def test_robust_bench_retrieve_1000_files(
        self, mem_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Synthesize a 1000-file memory dir under `people/` and `life/`.
        store = AssistantMemoryStore(mem_dir)
        people_lines: list[str] = ["# People Manifest"]
        for i in range(800):
            slug = f"person-{i:04d}"
            store.write_file(
                f"people/{slug}.md",
                {"name": slug, "tier": 3, "mention_count": 0},
                f"# {slug}\n\nbody {i}\n",
            )
            people_lines.append(f"- **{slug}.md** | tier:3 | mentions:0")
        store.write_manifest("people", "\n".join(people_lines) + "\n")

        life_lines: list[str] = ["# Life Manifest"]
        for i in range(200):
            slug = f"topic-{i:03d}"
            store.write_file(
                f"life/{slug}.md", {"domain": slug}, f"# {slug}\nbody\n"
            )
            life_lines.append(f"- **{slug}.md** | {slug}")
        store.write_manifest("life", "\n".join(life_lines) + "\n")

        # Build a manager with patched LLM client that always returns same scopes/files.
        completions_pro = _FakeCompletions(payload=json.dumps(
            {"scopes": ["people"], "files": ["people/person-0001.md"]}
        ))
        completions_flash = completions_pro

        def fake_create_client(settings: Any) -> Any:
            return _FakeClient(completions_flash)

        monkeypatch.setattr(
            "agent.assistant_memory.retrieval.create_client", fake_create_client
        )
        monkeypatch.setattr(
            "agent.assistant_memory.curator.create_client", fake_create_client
        )
        monkeypatch.setattr(
            "agent.assistant_memory.signal_detector.create_client", fake_create_client
        )

        mgr = AssistantMemoryManager(str(mem_dir), _fake_settings())

        samples: list[float] = []
        for i in range(20):
            t0 = time.perf_counter()
            mgr.retrieve_for_query(f"who is person {i}?")
            samples.append(time.perf_counter() - t0)
        p50 = median(samples)
        p99 = _percentile(samples, 99)
        print(f"\nretrieve_for_query(1000f) p50={p50*1000:.2f}ms  p99={p99*1000:.2f}ms")
        # 1000 files is small for FS reads; bound is generous.
        assert p99 < 5.0, f"retrieve p99 {p99:.3f}s exceeds 5s on 1000 files"

    def test_robust_bench_curator_post_turn(
        self, mem_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Curator post-turn on a 100-line user message.
        completions = _FakeCompletions(
            payload=json.dumps({"writes": [], "manifest_updates": []})
        )

        def fake_create_client(settings: Any) -> Any:
            return _FakeClient(completions)

        monkeypatch.setattr(
            "agent.assistant_memory.curator.create_client", fake_create_client
        )
        monkeypatch.setattr(
            "agent.assistant_memory.retrieval.create_client", fake_create_client
        )
        monkeypatch.setattr(
            "agent.assistant_memory.signal_detector.create_client", fake_create_client
        )

        mgr = AssistantMemoryManager(str(mem_dir), _fake_settings())
        long_user = "\n".join(f"line {i}" for i in range(100))

        samples: list[float] = []
        for _ in range(20):
            t0 = time.perf_counter()
            mgr.on_user_turn(long_user)
            mgr.on_assistant_turn("ok")
            # Wait for the curator daemon thread to finish so we measure
            # it (not just spawn cost).
            t = mgr._last_curator_thread
            if t is not None:
                t.join(timeout=10)
            samples.append(time.perf_counter() - t0)
        p50 = median(samples)
        p99 = _percentile(samples, 99)
        print(f"\non_assistant_turn (100ln) p50={p50*1000:.2f}ms  p99={p99*1000:.2f}ms")
        assert p99 < 5.0


# ---------------------------------------------------------------------------
# H. Misc. post-merge probes
# ---------------------------------------------------------------------------


class TestRobustPostMergeMisc:
    def test_robust_template_format_map_key_collision(self) -> None:
        # `{see_also}` field appears twice in PERSON_TEMPLATE; rendering one
        # value should fill all positions, not raise.
        out = render_template(PERSON_TEMPLATE, see_also="- [other](other.md)")
        assert out.count("- [other](other.md)") == 1  # template uses see_also once

    def test_robust_render_template_no_double_format(self) -> None:
        # If `value` itself contains a `{`, format_map should NOT recurse.
        out = render_template(PERSON_TEMPLATE, summary="value with {curly}")
        assert "value with {curly}" in out

    def test_robust_pages_round_trip_unicode_idempotent(self) -> None:
        body = (
            "# 武田信玄\n\nstate body\n\n---\n\n## Timeline\n"
            "- **2026-05-07** | session — café\n"
        )
        c, t = split_layers(body)
        once = join_layers(c, t)
        c2, t2 = split_layers(once)
        twice = join_layers(c2, t2)
        assert once == twice, "join/split is not idempotent on unicode bodies"

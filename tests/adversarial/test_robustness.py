"""Robustness / edge-case stress catalog for the assistant-memory subsystem.

Phase 1 of the adversarial-robustness role: enumerate pathological inputs,
unicode weirdness, frontmatter edges, two-layer page edges (Phase B surface),
tier escalation (Phase D), signal detector (Phase C), retrieval pathology,
filesystem chaos, and migration-script idempotency.

Each test is named ``test_robust_<area>_<scenario>`` per the coordination
rule with ``adversary-injection`` (which uses ``test_inject_*``). Tests that
target not-yet-implemented surfaces are skipped with a clear reason so they
can be re-run after merge of phases B / C / D.

All tests use pytest's ``tmp_path`` fixture; ``ASSISTANT_MEMORY_DIR`` is
pointed at the tmp dir so no test ever touches the real ``~/assistant-memory``.
"""

from __future__ import annotations

import importlib
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent.assistant_memory.curator import (
    Curator,
    extract_memory_notes,
    strip_memory_notes,
)
from agent.assistant_memory.schema import dump_frontmatter, parse_frontmatter
from agent.assistant_memory.signal_detector import SignalDetector, _empty_signals
from agent.assistant_memory.store import SCOPES, AssistantMemoryStore
from agent.assistant_memory.tiers import (
    TIER_1_RELATIONS,
    compute_tier,
    record_mention,
    should_write_compiled,
    update_people_manifest_line,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated assistant-memory root pointed at tmp."""
    monkeypatch.setenv("ASSISTANT_MEMORY_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def store(mem_dir: Path) -> AssistantMemoryStore:
    return AssistantMemoryStore(mem_dir)


# Helpers -------------------------------------------------------------------


def _has_attr(module_name: str, attr: str) -> bool:
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return False
    return hasattr(mod, attr)


# ---------------------------------------------------------------------------
# A. Pathological inputs
# ---------------------------------------------------------------------------


class TestRobustPathologicalInputs:
    """Empty / oversized / unicode / weird-name inputs."""

    def test_robust_pathological_empty_message(self, store: AssistantMemoryStore) -> None:
        # write_file with empty body should round-trip
        store.write_file("life/empty.md", {"k": "v"}, "")
        meta, body = store.read_file("life/empty.md")
        assert meta == {"k": "v"}
        assert body == ""

    def test_robust_pathological_whitespace_only_body(self, store: AssistantMemoryStore) -> None:
        store.write_file("life/ws.md", {"k": "v"}, "   \n\t\n   ")
        _, body = store.read_file("life/ws.md")
        # Body preserved; downstream code that strips will see empty
        assert body.strip() == ""

    def test_robust_pathological_emoji_only(self, store: AssistantMemoryStore) -> None:
        emoji = "🦄🌈🎉" * 100
        store.write_file("life/emoji.md", {"name": "🦄"}, emoji)
        meta, body = store.read_file("life/emoji.md")
        assert meta["name"] == "🦄"
        assert body.strip() == emoji

    def test_robust_pathological_one_megabyte_body(self, store: AssistantMemoryStore) -> None:
        big = "x" * (1024 * 1024)
        t0 = time.perf_counter()
        store.write_file("life/big.md", {"k": "v"}, big)
        _, body = store.read_file("life/big.md")
        elapsed = time.perf_counter() - t0
        assert len(body) >= 1024 * 1024
        # Pathology guard: 1MB round trip should be fast
        assert elapsed < 5.0, f"1MB round-trip took {elapsed:.2f}s"

    def test_robust_pathological_zero_width_joiner(self, store: AssistantMemoryStore) -> None:
        # Family ZWJ sequence
        s = "👨\u200d👩\u200d👧\u200d👦"
        store.write_file("life/zwj.md", {"name": s}, s)
        meta, body = store.read_file("life/zwj.md")
        assert meta["name"] == s
        assert s in body

    def test_robust_pathological_rtl_override(self, store: AssistantMemoryStore) -> None:
        # U+202E RIGHT-TO-LEFT OVERRIDE — should not corrupt YAML
        s = "hello\u202eevil"
        store.write_file("life/rtl.md", {"name": s}, s)
        meta, body = store.read_file("life/rtl.md")
        assert meta["name"] == s

    def test_robust_pathological_combining_diacritics(self, store: AssistantMemoryStore) -> None:
        s = "e" + ("\u0301" * 100)
        store.write_file("life/diacritic.md", {"name": s}, s)
        meta, _ = store.read_file("life/diacritic.md")
        assert meta["name"] == s

    def test_robust_pathological_mixed_scripts(self, store: AssistantMemoryStore) -> None:
        s = "武田信玄 + ∫f(x)dx + 🦄 + αβγ"
        store.write_file("life/mixed.md", {"name": s}, s)
        meta, _ = store.read_file("life/mixed.md")
        assert meta["name"] == s

    def test_robust_pathological_path_with_slash_rejected(self, store: AssistantMemoryStore) -> None:
        # `name/with/slashes` would mean a sub-path; safe_rel allows but
        # the slugifier (caller's responsibility) should normalize. Verify
        # at least that absolute / traversal forms are rejected.
        with pytest.raises(ValueError):
            store._safe_rel("../etc/passwd")
        with pytest.raises(ValueError):
            store._safe_rel("/etc/passwd")
        with pytest.raises(ValueError):
            store._safe_rel("life/../../etc/passwd")

    def test_robust_pathological_nul_byte_rejected(self, store: AssistantMemoryStore) -> None:
        with pytest.raises(ValueError):
            store._safe_rel("life/foo\x00bar.md")

    def test_robust_pathological_name_clashes_with_manifest(
        self, store: AssistantMemoryStore
    ) -> None:
        # If a "person" is somehow slugged to `_manifest`, writing
        # people/_manifest.md would clobber the manifest. The store does
        # NOT currently guard this — list_files filters _manifest.md from
        # results, so a person named "_manifest" disappears from listings.
        store.write_manifest("people", "# People Manifest\n")
        store.write_file("people/_manifest.md", {"name": "_manifest"}, "body")
        files = store.list_files("people")
        assert "people/_manifest.md" not in files, (
            "RISK: clobbered manifest is hidden from list_files — silent data loss"
        )


# ---------------------------------------------------------------------------
# B. Frontmatter edge cases
# ---------------------------------------------------------------------------


class TestRobustFrontmatter:
    def test_robust_frontmatter_no_frontmatter(self) -> None:
        meta, body = parse_frontmatter("just a body\nwith two lines\n")
        assert meta == {}
        assert body == "just a body\nwith two lines\n"

    def test_robust_frontmatter_empty_fences(self) -> None:
        meta, body = parse_frontmatter("---\n---\n\nbody here\n")
        assert meta == {}
        # Body is what's after the closing fence; empty frontmatter dict ok
        assert "body here" in body

    def test_robust_frontmatter_tier_string_vs_int(self, store: AssistantMemoryStore) -> None:
        # Phase D: compute_tier must coerce "1" or 1
        store.write_file("people/a.md", {"tier": "1", "mention_count": 0, "relation": ""}, "x")
        meta, _ = store.read_file("people/a.md")
        # YAML parses "1" as a string; compute_tier should still work
        tier = compute_tier(meta.get("mention_count", 0), str(meta.get("relation", "")))
        assert tier == 3  # because count is 0 and relation empty
        # And int form:
        assert compute_tier(1, "") == 3
        assert compute_tier(8, "") == 1

    def test_robust_frontmatter_extremely_many_keys(self) -> None:
        meta = {f"k{i}": i for i in range(10_000)}
        text = dump_frontmatter(meta, "body")
        t0 = time.perf_counter()
        parsed_meta, parsed_body = parse_frontmatter(text)
        elapsed = time.perf_counter() - t0
        assert len(parsed_meta) == 10_000
        assert parsed_body.strip() == "body"
        assert elapsed < 5.0, f"10k-key parse took {elapsed:.2f}s"

    def test_robust_frontmatter_yaml_anchor_trick(self) -> None:
        # YAML anchors should parse normally (yaml.safe_load supports them)
        text = "---\nbase: &a {x: 1}\nref: *a\n---\nbody\n"
        meta, body = parse_frontmatter(text)
        assert meta["base"] == {"x": 1}
        assert meta["ref"] == {"x": 1}

    def test_robust_frontmatter_recursive_anchor_handled(self) -> None:
        # Recursive anchor: yaml.safe_load typically permits it. Ensure no infinite loop.
        text = "---\na: &a\n  b: *a\n---\nbody\n"
        try:
            meta, _ = parse_frontmatter(text)
        except Exception:
            # Acceptable: yaml may reject. The point is no hang.
            return
        assert isinstance(meta, dict)

    def test_robust_frontmatter_block_scalar_with_dashes(self) -> None:
        # A `|` block scalar containing `---` lines must not split prematurely.
        text = (
            "---\n"
            "immutable_core: |\n"
            "  line one\n"
            "  ---\n"
            "  line three\n"
            "other: foo\n"
            "---\n"
            "real body\n"
        )
        meta, body = parse_frontmatter(text)
        assert meta.get("other") == "foo"
        assert "line one" in meta.get("immutable_core", "")
        assert body.strip() == "real body"

    def test_robust_frontmatter_malformed_yaml_falls_back(self) -> None:
        text = "---\n: : :\n---\nbody\n"
        meta, body = parse_frontmatter(text)
        # Malformed: returned as body-only
        assert meta == {}
        assert "body" in body


# ---------------------------------------------------------------------------
# C. Two-layer page edges (Phase B surface — may not yet exist)
# ---------------------------------------------------------------------------


def _has_page_module() -> bool:
    try:
        importlib.import_module("agent.assistant_memory.page")
        return True
    except Exception:
        return False


class TestRobustTwoLayerPages:
    """Phase B `## Timeline` separator semantics."""

    pytestmark = pytest.mark.skipif(
        not _has_page_module(),
        reason="Phase B page module not yet present (agent.assistant_memory.page)",
    )

    def test_robust_pages_split_layers_with_timeline_in_body(self) -> None:
        from agent.assistant_memory import page

        # `## Timeline (history)` heading inside compiled is NOT the canonical
        # separator (which requires the `\n\n---\n\n## Timeline\n` form).
        body = (
            "Compiled truth.\n## Timeline (history)\nmore context\n\n---\n\n"
            "## Timeline\n- **2026-05-07** | session — a\n"
        )
        compiled, timeline = page.split_layers(body)
        assert "Compiled truth" in compiled
        assert "## Timeline (history)" in compiled, "false-split: ate a real heading"
        assert "2026-05-07" in timeline

    def test_robust_pages_round_trip_idempotent(self) -> None:
        from agent.assistant_memory import page

        body = "compiled\n\n---\n\n## Timeline\n- **2026-05-07** | a\n"
        compiled, timeline = page.split_layers(body)
        joined = page.join_layers(compiled, timeline)
        # Round-trip should not multiply separators
        assert joined.count("\n---\n") == 1

    def test_robust_pages_empty_timeline(self) -> None:
        from agent.assistant_memory import page

        compiled, timeline = page.split_layers("just compiled\n")
        assert "just compiled" in compiled
        assert timeline.strip() == ""

    def test_robust_pages_huge_timeline_perf(self) -> None:
        from agent.assistant_memory import page

        big = "compiled\n\n---\n\n## Timeline\n" + "\n".join(
            f"- **2026-01-01** | session — event {i}" for i in range(100_000)
        )
        t0 = time.perf_counter()
        compiled, timeline = page.split_layers(big)
        joined = page.join_layers(compiled, timeline)
        elapsed = time.perf_counter() - t0
        assert "compiled" in compiled
        assert elapsed < 1.0, f"100k-line split/join took {elapsed:.2f}s"
        assert len(joined) >= len(big) - 100


# ---------------------------------------------------------------------------
# D. Tier escalation (Phase D)
# ---------------------------------------------------------------------------


class TestRobustTierEscalation:
    def test_robust_tier_negative_count_normalizes(self) -> None:
        # Corrupted disk value
        assert compute_tier(-5, "") == 3  # treated as low-count
        assert compute_tier(-1, "mom") == 1  # relation still wins

    def test_robust_tier_overflow_count(self) -> None:
        assert compute_tier(2**31, "") == 1  # >= 8 threshold

    def test_robust_tier_relation_case_normalized(self) -> None:
        # Stored as "MOM" or "Mom" — compute_tier lowercases
        assert compute_tier(0, "MOM") == 1
        assert compute_tier(0, "Mom") == 1
        assert compute_tier(0, "  mom  ") == 1
        # Non-tier-1 relation falls to tier 2
        assert compute_tier(0, "boss") == 2

    def test_robust_tier_record_mention_concurrent(self, store: AssistantMemoryStore) -> None:
        slug = "concurrent-alice"
        N_THREADS = 20

        errors: list[BaseException] = []

        def bump() -> None:
            try:
                record_mention(store, slug, "2026-05-07")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=bump) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"concurrent record_mention raised: {errors!r}"
        meta, _ = store.read_file(f"people/{slug}.md")
        # With the store's RLock, reads/writes are serialized so count == N
        assert meta["mention_count"] == N_THREADS, (
            f"Lost updates: expected {N_THREADS}, got {meta['mention_count']}"
        )

    def test_robust_tier_corrupt_count_recorded(self, store: AssistantMemoryStore) -> None:
        # Disk says count is "abc" — record_mention should normalize
        store.write_file(
            "people/garbage.md",
            {"mention_count": "abc", "relation": "", "tier": 3},
            "x",
        )
        meta = record_mention(store, "garbage", "2026-05-07")
        assert meta["mention_count"] == 1

    def test_robust_tier_should_write_compiled_corruption(self) -> None:
        # tier as string "garbage" — falls back to 3 (no compiled)
        assert should_write_compiled({"tier": "garbage"}) is False
        assert should_write_compiled({}) is False
        assert should_write_compiled({"tier": 1}) is True
        assert should_write_compiled({"tier": "2"}) is True

    def test_robust_tier_relations_constant_lowercase(self) -> None:
        # Defensive check on the constant
        for r in TIER_1_RELATIONS:
            assert r == r.lower(), f"TIER_1_RELATIONS contains non-lowercase: {r!r}"


# ---------------------------------------------------------------------------
# E. Signal detector (Phase C)
# ---------------------------------------------------------------------------


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, response: Any = None, raise_exc: BaseException | None = None,
                 hang: bool = False) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.hang = hang
        self.calls = 0

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.hang:
            time.sleep(60)  # signal detector has 10s timeout
        if self.raise_exc:
            raise self.raise_exc
        return self.response


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
        },
    )()


class TestRobustSignalDetector:
    def _make_detector(
        self,
        store: AssistantMemoryStore,
        completions: _FakeCompletions,
        monkeypatch: pytest.MonkeyPatch | None = None,
    ) -> SignalDetector:
        # Bypass real LLM client construction.
        if monkeypatch is not None:
            monkeypatch.setattr(
                "agent.assistant_memory.signal_detector.create_client",
                lambda settings: _FakeClient(completions),
            )
        det = SignalDetector.__new__(SignalDetector)
        det.store = store
        det.settings = _fake_settings()
        det.client = _FakeClient(completions)
        det.model_flash = "fake"
        return det

    def test_robust_signal_empty_user_msg(self, store: AssistantMemoryStore) -> None:
        comp = _FakeCompletions(_FakeResp("{}"))
        det = self._make_detector(store, comp)
        assert det.detect("", []) == _empty_signals()
        assert det.detect("   \n\t  ", []) == _empty_signals()
        assert comp.calls == 0  # short-circuit

    def test_robust_signal_llm_returns_empty_object(
        self, store: AssistantMemoryStore
    ) -> None:
        det = self._make_detector(store, _FakeCompletions(_FakeResp("{}")))
        out = det.detect("hello world", [])
        assert out == _empty_signals()

    def test_robust_signal_llm_returns_non_json(
        self, store: AssistantMemoryStore
    ) -> None:
        det = self._make_detector(store, _FakeCompletions(_FakeResp("not json")))
        out = det.detect("hello world", [])
        assert out == _empty_signals()

    def test_robust_signal_llm_returns_non_dict_json(
        self, store: AssistantMemoryStore
    ) -> None:
        det = self._make_detector(store, _FakeCompletions(_FakeResp("[1, 2, 3]")))
        out = det.detect("hello world", [])
        assert out == _empty_signals()

    def test_robust_signal_llm_invalid_entity_shapes(
        self, store: AssistantMemoryStore
    ) -> None:
        # entities: list with weird shapes — detector preserves raw list contents
        payload = (
            '{"entities": [{"slug": "", "name": null}, {"slug": "x", "name": "X"}],'
            ' "intentions": [], "events": [], "preferences": [], "corrections": []}'
        )
        det = self._make_detector(store, _FakeCompletions(_FakeResp(payload)))
        out = det.detect("Alice and Bob", [])
        # Detector forwards entries verbatim; downstream consumers must filter.
        assert isinstance(out["entities"], list)
        assert len(out["entities"]) == 2

    def test_robust_signal_llm_hang_returns_empty(
        self, store: AssistantMemoryStore
    ) -> None:
        # Patch the timeout to 0.5s for fast test
        det = self._make_detector(store, _FakeCompletions(hang=True))
        import agent.assistant_memory.signal_detector as sd

        orig = sd._DETECT_TIMEOUT_S
        sd._DETECT_TIMEOUT_S = 0.5
        try:
            t0 = time.perf_counter()
            out = det.detect("user message", [])
            elapsed = time.perf_counter() - t0
            assert out == _empty_signals()
            assert elapsed < 5.0, f"hang test took {elapsed:.2f}s — timeout broken"
        finally:
            sd._DETECT_TIMEOUT_S = orig

    def test_robust_signal_llm_raises(self, store: AssistantMemoryStore) -> None:
        det = self._make_detector(
            store, _FakeCompletions(raise_exc=RuntimeError("network down"))
        )
        out = det.detect("hello", [])
        assert out == _empty_signals()


# ---------------------------------------------------------------------------
# F. Retrieval pathology
# ---------------------------------------------------------------------------


class TestRobustRetrieval:
    def test_robust_retrieval_empty_index(self, store: AssistantMemoryStore) -> None:
        # _index.md doesn't exist -> read_index returns ""
        assert store.read_index() == ""

    def test_robust_retrieval_empty_manifest(self, store: AssistantMemoryStore) -> None:
        assert store.read_manifest("life") == ""

    def test_robust_retrieval_huge_manifest_size_warning(
        self, store: AssistantMemoryStore
    ) -> None:
        # 10MB manifest is a context-bomb risk for stage 2
        big = ("- " + ("x" * 100) + "\n") * 100_000  # ~10MB
        store.write_manifest("life", big)
        content = store.read_manifest("life")
        # Document the risk: file is read in full; downstream prompt would explode
        assert len(content) > 5_000_000, "test setup wrong"
        # Note: this is a HIGH risk finding — retrieval has no size guard.

    def test_robust_retrieval_unknown_scope_dropped_silently(
        self, store: AssistantMemoryStore
    ) -> None:
        # Stage 2 reads manifests by scope name. If LLM hallucinates a scope
        # name not in SCOPES (e.g., "secrets"), `read_manifest("secrets")`
        # would call `_safe_rel("secrets/_manifest.md")` which is allowed
        # since it's relative — but the file won't exist.
        # The risk: hallucinated scope is treated as a real (empty) scope.
        content = store.read_manifest("secrets")
        assert content == "", (
            "Hallucinated scope name silently produces empty manifest — "
            "callers should validate scope ∈ SCOPES first"
        )


# ---------------------------------------------------------------------------
# G. Filesystem chaos
# ---------------------------------------------------------------------------


class TestRobustFilesystem:
    def test_robust_fs_disk_full_no_corruption(
        self, store: AssistantMemoryStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Original write
        store.write_file("life/safe.md", {"k": "v"}, "original body")
        original = (store.root / "life" / "safe.md").read_text(encoding="utf-8")

        # Now make os.replace fail
        def boom(*args: Any, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            store.write_file("life/safe.md", {"k": "v"}, "new body")

        # Original file should be intact (atomic write contract)
        on_disk = (store.root / "life" / "safe.md").read_text(encoding="utf-8")
        assert on_disk == original, "atomic-write contract violated on disk-full"

    def test_robust_fs_symlink_traversal_blocked(self, store: AssistantMemoryStore) -> None:
        # Create symlink life/evil.md -> /etc/passwd
        target = Path("/etc/passwd")
        link = store.root / "life" / "evil.md"
        if not target.exists():
            pytest.skip("no /etc/passwd on this platform")
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

        # _safe_rel resolves the symlink. Since /etc/passwd is outside root,
        # relative_to(root) should raise.
        with pytest.raises(ValueError):
            store._safe_rel("life/evil.md")

    def test_robust_fs_case_collision_macos(self, store: AssistantMemoryStore) -> None:
        # On case-insensitive FS (macOS default), Alice.md and alice.md are
        # the same file. This is a HIGH risk for tier counters.
        store.write_file("people/Alice.md", {"name": "Alice", "mention_count": 1}, "A")
        store.write_file("people/alice.md", {"name": "alice", "mention_count": 99}, "a")

        files = store.list_files("people")
        # Document: on case-insensitive FS one of the two writes overwrites
        # the other. On case-sensitive FS, both coexist. Either way, the
        # downstream slug-keyed mention counter would mis-attribute mentions.
        if sys.platform == "darwin":
            # Likely just one file
            assert len(files) <= 2
        # Check both reads return some valid content
        m1, _ = store.read_file("people/Alice.md")
        m2, _ = store.read_file("people/alice.md")
        # At minimum, neither should crash
        assert isinstance(m1, dict) and isinstance(m2, dict)

    def test_robust_fs_readonly_dir_raises(
        self, mem_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = AssistantMemoryStore(mem_dir)
        # Make a scope dir read-only
        ro = store.root / "life"
        ro.chmod(0o500)
        try:
            with pytest.raises((OSError, PermissionError)):
                store.write_file("life/x.md", {}, "body")
        finally:
            ro.chmod(0o700)


# ---------------------------------------------------------------------------
# H. Migration script idempotency
# ---------------------------------------------------------------------------


class TestRobustMigration:
    def _run_migrate(self, env: dict[str, str]) -> subprocess.CompletedProcess:
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "migrate_personal_scopes.py"
        return subprocess.run(
            [sys.executable, str(script)],
            env={**os.environ, **env},
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_robust_migrate_no_projects_dir(self, tmp_path: Path) -> None:
        env = {"ASSISTANT_MEMORY_DIR": str(tmp_path)}
        result = self._run_migrate(env)
        assert result.returncode == 0
        assert "skip" in result.stdout

    def test_robust_migrate_idempotent(self, tmp_path: Path) -> None:
        env = {"ASSISTANT_MEMORY_DIR": str(tmp_path)}
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "a.md").write_text("# project a\n", encoding="utf-8")

        r1 = self._run_migrate(env)
        assert r1.returncode == 0
        legacy = tmp_path / "projects.legacy"
        assert legacy.exists(), "first run should rename projects -> projects.legacy"

        r2 = self._run_migrate(env)
        assert r2.returncode == 0
        assert "already" in r2.stdout or "skip" in r2.stdout

    def test_robust_migrate_empty_projects_dir(self, tmp_path: Path) -> None:
        env = {"ASSISTANT_MEMORY_DIR": str(tmp_path)}
        (tmp_path / "projects").mkdir()
        result = self._run_migrate(env)
        assert result.returncode == 0
        assert (tmp_path / "projects.legacy").exists()

    def test_robust_migrate_many_files(self, tmp_path: Path) -> None:
        env = {"ASSISTANT_MEMORY_DIR": str(tmp_path)}
        projects = tmp_path / "projects"
        projects.mkdir()
        for i in range(200):  # 1000 is excessive for CI; 200 still stresses
            (projects / f"p{i}.md").write_text(f"# project {i}\nbody\n", encoding="utf-8")
        t0 = time.perf_counter()
        result = self._run_migrate(env)
        elapsed = time.perf_counter() - t0
        assert result.returncode == 0, result.stderr
        archive = tmp_path / "life" / "_archive_from_projects.md"
        assert archive.exists()
        text = archive.read_text(encoding="utf-8")
        # All 200 files should appear
        for i in range(200):
            assert f"p{i}.md" in text, f"p{i}.md missing from archive"
        assert elapsed < 30.0

    def test_robust_migrate_non_utf8_file(self, tmp_path: Path) -> None:
        # FINDING (HIGH): migrate_personal_scopes.py wraps read_text() in
        # try/except OSError, but UnicodeDecodeError is NOT an OSError. A
        # single non-utf8 file crashes the whole migration AFTER zero work,
        # so users with one corrupt project file lose nothing — but they
        # also can't migrate at all without manual cleanup.
        env = {"ASSISTANT_MEMORY_DIR": str(tmp_path)}
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "bad.md").write_bytes(b"\xff\xfe non-utf8 bytes\n")
        (projects / "ok.md").write_text("# ok\n", encoding="utf-8")

        result = self._run_migrate(env)
        # Document the bug: expected graceful skip, observed full crash.
        assert result.returncode != 0, "non-utf8 handling regressed?"
        assert "UnicodeDecodeError" in result.stderr, (
            "expected the known UnicodeDecodeError crash; saw something else"
        )
        # And projects.legacy was NOT created — migration aborted.
        assert not (tmp_path / "projects.legacy").exists()


# ---------------------------------------------------------------------------
# Memory-note marker robustness (Curator parsing surface)
# ---------------------------------------------------------------------------


class TestRobustMemoryNotes:
    def test_robust_notes_strip_collapses_blanks(self) -> None:
        text = "before\n\n[memory note: x]\n\n\nafter"
        cleaned = strip_memory_notes(text)
        assert "[memory note" not in cleaned
        assert "before" in cleaned and "after" in cleaned

    def test_robust_notes_extract_multiple(self) -> None:
        text = "[memory note: a] mid [memory note: b]"
        notes = extract_memory_notes(text)
        assert notes == ["a", "b"]

    def test_robust_notes_multiline_marker(self) -> None:
        text = "[memory note: line1\nline2]"
        notes = extract_memory_notes(text)
        assert len(notes) == 1 and "line1" in notes[0] and "line2" in notes[0]

    def test_robust_notes_empty_input(self) -> None:
        assert extract_memory_notes("") == []
        assert extract_memory_notes(None) == []  # type: ignore[arg-type]
        assert strip_memory_notes("") == ""

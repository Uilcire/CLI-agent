"""Tests for AssistantMemoryManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.assistant_memory.manager import AssistantMemoryManager
from agent.config.settings import Settings


def _settings() -> Settings:
    return Settings(
        backend="deepseek",
        api_key="test-key",
        model="deepseek-v4-pro",
        max_tokens=1024,
        base_url="https://example.invalid",
        model_pro="deepseek-v4-pro",
        model_flash="deepseek-v4-flash",
    )


@pytest.fixture
def manager(tmp_path: Path) -> AssistantMemoryManager:
    with patch("agent.assistant_memory.retrieval.create_client") as r_mock, patch(
        "agent.assistant_memory.curator.create_client"
    ) as c_mock:
        r_mock.return_value = MagicMock()
        c_mock.return_value = MagicMock()
        m = AssistantMemoryManager(data_dir=str(tmp_path), settings=_settings())
    return m


def test_on_startup_returns_context_block(manager: AssistantMemoryManager):
    manager.store.write_file(
        "identity/agent.md",
        {"immutable_core": "I am a faithful assistant."},
        "I have curiosity and patience.\n",
    )
    manager.store.write_index(
        "---\nuser_summary: Eric — CS student.\n---\n\n# Memory Index\n"
    )
    manager.store.write_file("context/current.md", {}, "Working on CLI agent Phase 2.\n")

    block = manager.on_startup(project_id=None)
    assert "I am a faithful assistant." in block
    assert "I have curiosity and patience." in block
    assert "Eric — CS student." in block
    assert "Working on CLI agent Phase 2." in block


def test_on_user_and_assistant_turn_caps_at_six(manager: AssistantMemoryManager):
    # Disable curator side-effects.
    manager.curator.propose_writes = MagicMock(return_value={"writes": [], "manifest_updates": []})
    manager.curator.apply_writes = MagicMock(return_value=[])
    manager.curator.apply_manifest_updates = MagicMock()

    for i in range(5):
        manager.on_user_turn(f"u{i}")
        manager.on_assistant_turn(f"a{i}")

    assert len(manager.recent_turns) == 6
    # Should hold the most recent 6 messages: u2,a2,u3,a3,u4,a4
    assert manager.recent_turns[0]["content"] == "u2"
    assert manager.recent_turns[-1]["content"] == "a4"
    # Active session messages keep all 10.
    assert len(manager._active_session_messages) == 10


def test_on_assistant_turn_invokes_curator(manager: AssistantMemoryManager):
    manager.curator.propose_writes = MagicMock(
        return_value={"writes": [], "manifest_updates": [{"x": 1}]}
    )
    manager.curator.apply_writes = MagicMock(return_value=[])
    manager.curator.apply_manifest_updates = MagicMock()

    manager.on_user_turn("hi")
    manager.on_assistant_turn("hello")

    manager.curator.propose_writes.assert_called_once()
    manager.curator.apply_writes.assert_called_once()
    manager.curator.apply_manifest_updates.assert_called_once_with([{"x": 1}])


def test_find_project_for_cwd_hit_and_miss(manager: AssistantMemoryManager, tmp_path: Path):
    cwd = str(tmp_path / "demo-proj")
    Path(cwd).mkdir()
    # Miss when no file present.
    assert manager.find_project_for_cwd(cwd) is None

    from agent.assistant_memory.manager import _cwd_project_id
    pid = _cwd_project_id(cwd)
    manager.store.write_file(
        f"projects/{pid}.md",
        {"project_id": pid, "cwd": cwd, "status": "active", "tags": ["foo"]},
        f"# {pid}\n\n## Description\n\nA cool project.\n",
    )
    view = manager.find_project_for_cwd(cwd)
    assert view is not None
    assert view.project_id == pid
    assert view.cwd == cwd
    assert "foo" in view.tags


def test_onboard_for_cwd_creates_markdown(manager: AssistantMemoryManager, tmp_path: Path):
    cwd = str(tmp_path / "fresh-proj")
    Path(cwd).mkdir()
    view = manager.onboard_for_cwd(cwd, print_fn=lambda *_: None)
    assert view is not None

    from agent.assistant_memory.manager import _cwd_project_id
    pid = _cwd_project_id(cwd)
    md_path = Path(manager.data_dir) / "projects" / f"{pid}.md"
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "## Description" in text
    assert pid in text
    # Manifest updated.
    manifest = manager.store.read_manifest("projects")
    assert pid in manifest


def test_handle_command_list_people(manager: AssistantMemoryManager):
    manager.store.write_file("people/alex.md", {"name": "alex"}, "# Alex\n")
    manager.store.write_file("people/mom.md", {"name": "mom"}, "# Mom\n")
    out = manager.handle_command("/memory list people")
    assert out is not None
    assert "people/alex.md" in out
    assert "people/mom.md" in out


def test_handle_command_help(manager: AssistantMemoryManager):
    assert manager.handle_command("/memory") is not None
    assert manager.handle_command("/memory help") is not None
    assert manager.handle_command("/skills") is None


def test_on_exit_returns_background_message(manager: AssistantMemoryManager):
    manager.curator.propose_writes = MagicMock(return_value={"writes": [], "manifest_updates": []})
    manager.curator.apply_writes = MagicMock(return_value=[])
    manager.curator.apply_manifest_updates = MagicMock()
    manager.curator.summarize_session = MagicMock()

    manager.on_user_turn("hi")
    manager.on_assistant_turn("hello")
    msg = manager.on_exit()
    assert msg is not None and "background" in msg.lower()


def test_on_exit_returns_none_when_empty(manager: AssistantMemoryManager):
    assert manager.on_exit() is None


# ---- New tests: retrieval wiring + on_exit ordering + projectview rename ----


def test_retrieve_for_query_returns_memories(manager: AssistantMemoryManager):
    manager.retrieval.retrieve = MagicMock(  # type: ignore[assignment]
        return_value={
            "files": ["people/alex.md"],
            "current_context": "Working on Phase 2.",
            "user_summary": "Eric — CS student.",
            "agent_soul": "",
            "immutable_core": "",
            "file_contents": {"people/alex.md": "# Alex\n\nGirlfriend, SF."},
        }
    )

    block = manager.retrieve_for_query("when is alex's birthday?")
    assert "# Retrieved memories" in block
    assert "=== people/alex.md ===" in block
    assert "Girlfriend, SF." in block
    assert "context/current.md" in block
    assert "Working on Phase 2." in block
    assert "Eric — CS student." in block


def test_retrieve_for_query_empty_when_no_files(manager: AssistantMemoryManager):
    manager.retrieval.retrieve = MagicMock(  # type: ignore[assignment]
        return_value={
            "files": [],
            "current_context": "",
            "user_summary": "",
            "agent_soul": "",
            "immutable_core": "",
            "file_contents": {},
        }
    )
    assert manager.retrieve_for_query("hello") == ""


def test_retrieve_for_query_handles_failure_silently(manager: AssistantMemoryManager):
    manager.retrieval.retrieve = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[assignment]
    assert manager.retrieve_for_query("anything") == ""


def test_on_exit_joins_curator_thread(manager: AssistantMemoryManager):
    import threading
    import time

    started = threading.Event()
    finished = threading.Event()

    def slow_propose(*_args, **_kwargs):
        started.set()
        time.sleep(0.1)
        finished.set()
        return {"writes": [], "manifest_updates": []}

    manager.curator.propose_writes = MagicMock(side_effect=slow_propose)
    manager.curator.apply_writes = MagicMock(return_value=[])
    manager.curator.apply_manifest_updates = MagicMock()
    manager.curator.consolidate_session = MagicMock()
    manager.curator.summarize_session = MagicMock()

    manager.on_user_turn("hi")
    manager.on_assistant_turn("hello")
    started.wait(timeout=1.0)

    msg = manager.on_exit()
    assert msg is not None
    # By the time on_exit returns, the per-turn curator should have completed
    # (it joined with timeout=2.0 and the work takes ~100ms).
    assert finished.is_set()


def test_on_exit_runs_consolidate_then_summarize(manager: AssistantMemoryManager):
    import threading

    manager.curator.propose_writes = MagicMock(return_value={"writes": [], "manifest_updates": []})
    manager.curator.apply_writes = MagicMock(return_value=[])
    manager.curator.apply_manifest_updates = MagicMock()

    consolidate_done = threading.Event()
    summarize_done = threading.Event()
    manager.curator.consolidate_session = MagicMock(side_effect=lambda *_a, **_k: consolidate_done.set())
    manager.curator.summarize_session = MagicMock(side_effect=lambda *_a, **_k: summarize_done.set())

    manager.on_user_turn("hi")
    manager.on_assistant_turn("hello")
    manager.on_exit()

    assert consolidate_done.wait(timeout=2.0)
    assert summarize_done.wait(timeout=2.0)
    manager.curator.consolidate_session.assert_called_once()
    manager.curator.summarize_session.assert_called_once()


def test_projectview_rename():
    from agent.assistant_memory import manager as m

    assert hasattr(m, "ProjectView")
    # Back-compat alias should still resolve to the same class.
    assert m.MigratedProjectView is m.ProjectView
    # `sessions` field has been dropped.
    pv = m.ProjectView(project_id="p1")
    assert not hasattr(pv, "sessions")


def test_strip_memory_notes_in_display():
    from agent.cli.display import _MemNoteFilter

    f = _MemNoteFilter()
    out = f.feed("Hello [memory note: alex likes coffee] world")
    out += f.flush()
    assert "memory note" not in out
    assert "Hello " in out and " world" in out

    # Streamed char-by-char.
    f2 = _MemNoteFilter()
    chunks = "Hi [memory note: x] bye"
    streamed = "".join(f2.feed(c) for c in chunks) + f2.flush()
    assert "memory note" not in streamed
    assert streamed == "Hi  bye"

"""Tests for SessionManager and MemoryManager."""

import pytest

from agent.config.settings import Settings
from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.memory.models import Personality
from agent.memory.session import SessionManager
from agent.memory.store import LocalMemoryStore

# Minimal settings for tests (no real API calls in these tests)
_TEST_SETTINGS = Settings(
    backend="openai",
    api_key="sk-test",
    model="gpt-4",
    max_tokens=100,
)


def test_start_creates_and_persists_session(tmp_path: pytest.TempPathFactory) -> None:
    """start() creates a session and persists it to disk."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    manager = SessionManager(store, config, _TEST_SETTINGS)

    session = manager.start()
    assert session.session_id
    assert len(session.session_id) > 0

    loaded = store.load_active_session(session.session_id)
    assert loaded is not None
    assert loaded.session_id == session.session_id


def test_record_turn_appends_and_persists(tmp_path: pytest.TempPathFactory) -> None:
    """record_turn() appends messages and persists to disk."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    manager = SessionManager(store, config, _TEST_SETTINGS)

    session = manager.start()
    manager.record_turn(session, "user", "hello")
    manager.record_turn(session, "user", "world")

    loaded = store.load_active_session(session.session_id)
    assert loaded is not None
    assert len(loaded.messages) == 2
    assert loaded.messages[0] == {"role": "user", "content": "hello"}
    assert loaded.messages[1] == {"role": "user", "content": "world"}


def test_end_deletes_session_from_disk(tmp_path: pytest.TempPathFactory) -> None:
    """end() deletes the session file from disk."""
    store = LocalMemoryStore(str(tmp_path))
    config = MemoryConfig(data_dir=str(tmp_path))
    manager = SessionManager(store, config, _TEST_SETTINGS)

    session = manager.start()
    assert store.load_active_session(session.session_id) is not None

    manager.end(session)
    assert store.load_active_session(session.session_id) is None


def test_memory_manager_on_startup_returns_empty_when_no_memory(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """MemoryManager.on_startup() returns empty string when no personality/project exists."""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    result = memory.on_startup()
    assert result == ""


def test_memory_manager_on_startup_returns_context_when_personality_exists(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """MemoryManager.on_startup() returns context string when personality exists."""
    store = LocalMemoryStore(str(tmp_path))
    p = Personality(soul="be helpful", immutable_core="always honest")
    store.save_personality(p)

    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    result = memory.on_startup()
    assert "be helpful" in result
    assert "always honest" in result


def test_memory_manager_swallows_exceptions(tmp_path: pytest.TempPathFactory) -> None:
    """MemoryManager swallows store exceptions and returns empty string."""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory._store.get_personality = lambda: (_ for _ in ()).throw(RuntimeError("boom"))

    result = memory.on_startup()
    assert result == ""


def test_turn_recording_via_manager_persists_to_disk(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """on_user_turn and on_assistant_turn persist messages to disk."""
    memory = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    memory.on_startup()
    memory.on_user_turn("hi")
    memory.on_assistant_turn("hello")

    store = LocalMemoryStore(str(tmp_path))
    sessions = store.list_active_sessions()
    assert len(sessions) == 1
    loaded = store.load_active_session(sessions[0]["session_id"])
    assert loaded is not None
    assert len(loaded.messages) == 2
    assert loaded.messages[0] == {"role": "user", "content": "hi"}
    assert loaded.messages[1] == {"role": "assistant", "content": "hello"}

"""Tests for /memory init and /memory personality commands. Use tmp_path and _TEST_SETTINGS."""

import pytest

from agent.config.settings import Settings
from agent.memory.manager import MemoryManager
from agent.memory.models import Personality
from agent.memory.store import LocalMemoryStore

_TEST_SETTINGS = Settings(
    backend="openai",
    api_key="sk-test",
    model="gpt-4",
    max_tokens=100,
)


def test_init_creates_personality(tmp_path: pytest.TempPathFactory) -> None:
    """Fresh store, call /memory init — personality created, response contains 'Soul initialised'."""
    store = LocalMemoryStore(str(tmp_path))
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager._store = store
    manager.on_startup()

    result = manager.handle_command("/memory init")

    assert manager._store.get_personality() is not None
    assert result is not None
    assert "Soul initialised" in result


def test_init_twice_warns(tmp_path: pytest.TempPathFactory) -> None:
    """Call /memory init twice — second returns 'already exists'."""
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()

    manager.handle_command("/memory init")
    result2 = manager.handle_command("/memory init")

    assert "already exists" in result2


def test_personality_show_no_personality(tmp_path: pytest.TempPathFactory) -> None:
    """Fresh store, /memory personality show returns 'No soul configured'."""
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()

    result = manager.handle_command("/memory personality show")

    assert result is not None
    assert "No soul configured" in result


def test_personality_show_displays_both_fields(tmp_path: pytest.TempPathFactory) -> None:
    """Seed personality with known soul and core — show output contains both."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_personality(
        Personality(soul="My custom soul.", immutable_core="My immutable core.")
    )
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()

    result = manager.handle_command("/memory personality show")

    assert result is not None
    assert "My custom soul." in result
    assert "My immutable core." in result


def test_personality_set_soul_updates(tmp_path: pytest.TempPathFactory) -> None:
    """Init, then set soul — store has new soul, response is 'Soul updated.'"""
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()
    manager.handle_command("/memory init")

    result = manager.handle_command('/memory personality set soul "new soul text"')

    assert result == "Soul updated."
    p = manager._store.get_personality()
    assert p is not None
    assert p.soul == "new soul text"


def test_personality_set_soul_empty_text(tmp_path: pytest.TempPathFactory) -> None:
    """Set soul with empty text — returns usage string, store unchanged."""
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()
    manager.handle_command("/memory init")
    original_soul = manager._store.get_personality()
    assert original_soul is not None

    result = manager.handle_command("/memory personality set soul \"\"")

    assert "Usage" in result
    p = manager._store.get_personality()
    assert p is not None
    assert p.soul == original_soul.soul


def test_personality_set_core_replaces(tmp_path: pytest.TempPathFactory) -> None:
    """Init with core 'old core', set core 'new core' — store has new core."""
    store = LocalMemoryStore(str(tmp_path))
    store.save_personality(
        Personality(soul="soul", immutable_core="old core")
    )
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()

    manager.handle_command('/memory personality set core "new core"')

    p = manager._store.get_personality()
    assert p is not None
    assert p.immutable_core == "new core"


def test_personality_set_soul_no_personality(tmp_path: pytest.TempPathFactory) -> None:
    """No init, call set soul — returns 'No soul configured'."""
    manager = MemoryManager(data_dir=str(tmp_path), settings=_TEST_SETTINGS)
    manager.on_startup()

    result = manager.handle_command('/memory personality set soul "x"')

    assert "No soul configured" in result

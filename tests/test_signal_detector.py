"""Tests for the user-side signal detector (Phase C)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.assistant_memory.signal_detector import SignalDetector
from agent.assistant_memory.store import AssistantMemoryStore
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
def store(tmp_path: Path) -> AssistantMemoryStore:
    return AssistantMemoryStore(tmp_path)


def _mock_response(content: str) -> MagicMock:
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


def _detector(store: AssistantMemoryStore, response: MagicMock) -> SignalDetector:
    with patch("agent.assistant_memory.signal_detector.create_client") as mock_create:
        client = MagicMock()
        client.chat.completions.create.return_value = response
        mock_create.return_value = client
        det = SignalDetector(store, _settings())
    return det


def test_detect_parses_known_json(store: AssistantMemoryStore):
    payload = (
        '{"entities": [{"type": "person", "name": "Alex", "slug": "alex"}], '
        '"intentions": ["learn rust"], '
        '"events": [{"when": "2026-05-10", "what": "offsite"}], '
        '"preferences": ["likes oat milk"], '
        '"corrections": []}'
    )
    det = _detector(store, _mock_response(payload))
    out = det.detect("Alex and I are doing the offsite May 10.", [])
    assert out["entities"] == [{"type": "person", "name": "Alex", "slug": "alex"}]
    assert out["intentions"] == ["learn rust"]
    assert out["events"] == [{"when": "2026-05-10", "what": "offsite"}]
    assert out["preferences"] == ["likes oat milk"]
    assert out["corrections"] == []


def test_detect_returns_empty_on_invalid_json(store: AssistantMemoryStore):
    det = _detector(store, _mock_response("not valid json {{"))
    out = det.detect("hi", [])
    assert out == {
        "entities": [],
        "intentions": [],
        "events": [],
        "preferences": [],
        "corrections": [],
    }


def test_detect_returns_empty_on_empty_user_msg(store: AssistantMemoryStore):
    det = _detector(store, _mock_response("{}"))
    # Should short-circuit before calling LLM.
    out = det.detect("", [])
    assert out["entities"] == []
    assert out["intentions"] == []


def test_detect_returns_empty_on_llm_exception(store: AssistantMemoryStore):
    with patch("agent.assistant_memory.signal_detector.create_client") as mock_create:
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("boom")
        mock_create.return_value = client
        det = SignalDetector(store, _settings())
    out = det.detect("hello there", [])
    assert out["entities"] == []
    assert out["preferences"] == []


def test_detect_ignores_non_list_fields(store: AssistantMemoryStore):
    # Model returns a malformed shape — keys present but wrong types.
    payload = '{"entities": "not a list", "intentions": null, "preferences": ["ok"]}'
    det = _detector(store, _mock_response(payload))
    out = det.detect("hi", [])
    assert out["entities"] == []
    assert out["intentions"] == []
    assert out["preferences"] == ["ok"]


def test_detect_does_not_block_main_thread(store: AssistantMemoryStore):
    """Spawning detect() in a background thread must not block the spawning thread."""

    def slow_create(*args, **kwargs):
        time.sleep(2.0)
        return _mock_response('{"entities": []}')

    with patch("agent.assistant_memory.signal_detector.create_client") as mock_create:
        client = MagicMock()
        client.chat.completions.create.side_effect = slow_create
        mock_create.return_value = client
        det = SignalDetector(store, _settings())

    result_box: dict = {}

    def _run():
        result_box["out"] = det.detect("test", [])

    worker = threading.Thread(target=_run, daemon=True)

    t0 = time.monotonic()
    worker.start()
    # Main thread should resume immediately — well under the 2s sleep.
    spawn_elapsed = time.monotonic() - t0
    assert spawn_elapsed < 0.5, f"spawn blocked for {spawn_elapsed:.2f}s"

    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert "out" in result_box

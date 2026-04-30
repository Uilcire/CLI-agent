"""Tests for the assistant memory two-stage retrieval pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.assistant_memory.retrieval import RetrievalPipeline
from agent.assistant_memory.store import AssistantMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> AssistantMemoryStore:
    s = AssistantMemoryStore(tmp_path)
    s.write_index(
        "---\nuser_summary: \"Eric — CS student.\"\nlast_rebuilt: 2026-04-29\n---\n\n"
        "# Memory Index\n\n## Scopes\n- people/ — 1 person\n- preferences/ — 1 area\n"
    )
    s.write_manifest(
        "people",
        "# People Manifest\n\n- **alex.md** | Girlfriend | SF\n",
    )
    s.write_file(
        "people/alex.md",
        {"name": "alex", "relation": "girlfriend"},
        "# Alex\n\nGirlfriend in SF.\n",
    )
    s.write_manifest(
        "preferences",
        "# Preferences Manifest\n\n- **gifts.md** | gift-giving habits\n",
    )
    s.write_file(
        "preferences/gifts.md",
        {"topic": "gifts"},
        "# Gifts\n\nBudget around $100.\n",
    )
    s.write_file(
        "context/current.md",
        {},
        "Current week: shipping memory system.\n",
    )
    s.write_file(
        "identity/agent.md",
        {"immutable_core": "Be helpful and honest."},
        "I am the assistant.\n",
    )
    return s


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        backend="deepseek",
        api_key="test-key",
        base_url="https://example.invalid",
        model_flash="deepseek-v4-flash",
        model_pro="deepseek-v4-pro",
        model="legacy",
        gpt_endpoint="",
        gpt_api_version="",
    )


def _mock_response(payload: str) -> MagicMock:
    msg = MagicMock()
    msg.content = payload
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_client(payloads: list[str]) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _mock_response(p) for p in payloads
    ]
    return client


def test_stage1_returns_expected_scopes(store: AssistantMemoryStore) -> None:
    client = _make_client([
        json.dumps({"scopes": ["people"], "reasoning": "asks about alex"}),
    ])
    with patch("agent.assistant_memory.retrieval.create_client", return_value=client):
        pipeline = RetrievalPipeline(store, _settings())
    result = pipeline.select_scopes("How is Alex?", [])
    assert result.scopes == ["people"]
    assert "alex" in result.reasoning


def test_stage2_caps_at_5_files(store: AssistantMemoryStore) -> None:
    too_many = [f"people/p{i}.md" for i in range(10)]
    client = _make_client([
        json.dumps({"files": too_many, "reasoning": "many"}),
    ])
    with patch("agent.assistant_memory.retrieval.create_client", return_value=client):
        pipeline = RetrievalPipeline(store, _settings())
    files = pipeline.select_files("anything", [], ["people"])
    assert len(files) == 5
    assert files == too_many[:5]


def test_stage1_malformed_json_falls_back_to_all_scopes(
    store: AssistantMemoryStore,
) -> None:
    client = _make_client(["not valid json at all"])
    with patch("agent.assistant_memory.retrieval.create_client", return_value=client):
        pipeline = RetrievalPipeline(store, _settings())
    result = pipeline.select_scopes("x", [])
    # All scopes except `context` should be returned
    assert "people" in result.scopes
    assert "preferences" in result.scopes
    assert "identity" in result.scopes
    assert "context" not in result.scopes
    assert "fallback" in result.reasoning


def test_retrieve_end_to_end_shape(store: AssistantMemoryStore) -> None:
    client = _make_client([
        json.dumps({"scopes": ["people", "preferences"], "reasoning": "r1"}),
        json.dumps({"files": ["people/alex.md", "preferences/gifts.md"], "reasoning": "r2"}),
    ])
    with patch("agent.assistant_memory.retrieval.create_client", return_value=client):
        pipeline = RetrievalPipeline(store, _settings())
    recent = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = pipeline.retrieve("What should I get Alex?", recent)
    assert set(out.keys()) == {
        "files",
        "current_context",
        "user_summary",
        "agent_soul",
        "immutable_core",
        "file_contents",
    }
    assert out["files"] == ["people/alex.md", "preferences/gifts.md"]
    assert "shipping memory system" in out["current_context"]
    assert out["user_summary"].startswith("Eric")
    assert "assistant" in out["agent_soul"]
    assert out["immutable_core"] == "Be helpful and honest."
    assert "Alex" in out["file_contents"]["people/alex.md"]
    assert "Budget" in out["file_contents"]["preferences/gifts.md"]


def test_empty_current_and_missing_agent_handled(tmp_path: Path) -> None:
    store = AssistantMemoryStore(tmp_path)
    store.write_index("# index\n")
    store.write_manifest("people", "# people\n")
    client = _make_client([
        json.dumps({"scopes": [], "reasoning": "nothing"}),
    ])
    with patch("agent.assistant_memory.retrieval.create_client", return_value=client):
        pipeline = RetrievalPipeline(store, _settings())
    out = pipeline.retrieve("hello", [])
    assert out["files"] == []
    assert out["current_context"] == ""
    assert out["agent_soul"] == ""
    assert out["immutable_core"] == ""
    assert out["user_summary"] == ""
    assert out["file_contents"] == {}

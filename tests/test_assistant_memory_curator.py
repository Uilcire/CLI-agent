"""Tests for the assistant memory curator."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.assistant_memory.curator import (
    Curator,
    extract_memory_notes,
    strip_memory_notes,
)
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


def _mock_llm_response(content: str) -> MagicMock:
    """Build a fake openai-style chat completion response with `content`."""
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


# ---- extract / strip ----------------------------------------------------


def test_extract_memory_notes_finds_multiple():
    text = (
        "Hello there. [memory note: alex likes oat milk]\n"
        "Some prose. [memory note: prefers SF restaurants]"
    )
    notes = extract_memory_notes(text)
    assert notes == ["alex likes oat milk", "prefers SF restaurants"]


def test_extract_memory_notes_empty():
    assert extract_memory_notes("") == []
    assert extract_memory_notes("no markers here") == []


def test_strip_memory_notes_removes_cleanly():
    text = "Reply body. [memory note: foo]\nLine two. [memory note: bar]"
    cleaned = strip_memory_notes(text)
    assert "memory note" not in cleaned
    assert "Reply body." in cleaned
    assert "Line two." in cleaned


# ---- apply_writes -------------------------------------------------------


def test_apply_writes_layer1_append(store: AssistantMemoryStore):
    # Seed an existing file.
    store.write_file("preferences/food.md", {"topic": "food"}, "# Food\n\n- existing fact\n")

    with patch("agent.assistant_memory.curator.create_client") as mock_create:
        mock_create.return_value = MagicMock()
        curator = Curator(store, _settings())

    proposal = {
        "writes": [
            {
                "file": "preferences/food.md",
                "operation": "append",
                "content": "- allergic to peanuts",
                "layer": 1,
                "compiled_update": True,
                "source_type": "self-described",
                "reason": "user said so",
            }
        ],
        "manifest_updates": [],
    }
    applied = curator.apply_writes(proposal)
    assert applied == ["Appended to preferences/food.md"]

    _, body = store.read_file("preferences/food.md")
    assert "existing fact" in body
    assert "allergic to peanuts" in body


def test_apply_writes_layer2_rejected(store: AssistantMemoryStore):
    store.write_file("people/alex.md", {"name": "alex"}, "# Alex\n")

    with patch("agent.assistant_memory.curator.create_client") as mock_create:
        mock_create.return_value = MagicMock()
        curator = Curator(store, _settings())

    proposal = {
        "writes": [
            {
                "file": "people/alex.md",
                "operation": "append",
                "content": "- moved to NYC",
                "layer": 2,
                "reason": "ambiguous",
            }
        ],
        "manifest_updates": [],
    }
    applied = curator.apply_writes(proposal, confirm_callback=lambda w: False)
    assert applied == []

    _, body = store.read_file("people/alex.md")
    assert "moved to NYC" not in body


def test_apply_writes_layer2_no_callback_skips(store: AssistantMemoryStore):
    store.write_file("people/alex.md", {"name": "alex"}, "# Alex\n")

    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())

    proposal = {
        "writes": [
            {
                "file": "people/alex.md",
                "operation": "append",
                "content": "- moved to NYC",
                "layer": 2,
            }
        ],
        "manifest_updates": [],
    }
    applied = curator.apply_writes(proposal, confirm_callback=None)
    assert applied == []


def test_apply_writes_update_field(store: AssistantMemoryStore):
    store.write_file("people/alex.md", {"name": "alex", "location": "SF"}, "# Alex\n")
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())

    proposal = {
        "writes": [
            {
                "file": "people/alex.md",
                "operation": "update_field",
                "field": "location",
                "value": "NYC",
                "layer": 1,
            }
        ],
        "manifest_updates": [],
    }
    curator.apply_writes(proposal)
    meta, _ = store.read_file("people/alex.md")
    assert meta["location"] == "NYC"


# ---- manifest -----------------------------------------------------------


def test_apply_manifest_updates_replaces_line(store: AssistantMemoryStore):
    store.write_manifest(
        "people",
        "# People Manifest\n\n- **alex.md** | old line\n- **mom.md** | mother\n",
    )
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())

    curator.apply_manifest_updates(
        [{"scope": "people", "line_key": "**alex.md**", "new_line": "- **alex.md** | new line"}]
    )
    content = store.read_manifest("people")
    assert "- **alex.md** | new line" in content
    assert "old line" not in content
    assert "mom.md" in content  # untouched


def test_apply_manifest_updates_appends_when_missing(store: AssistantMemoryStore):
    store.write_manifest("people", "# People Manifest\n\n- **mom.md** | mother\n")
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())

    curator.apply_manifest_updates(
        [{"scope": "people", "line_key": "**alex.md**", "new_line": "- **alex.md** | new"}]
    )
    content = store.read_manifest("people")
    assert "- **alex.md** | new" in content
    assert "mom.md" in content


# ---- propose_writes -----------------------------------------------------


def test_propose_writes_parses_json(store: AssistantMemoryStore):
    payload = {
        "writes": [
            {
                "file": "preferences/food.md",
                "operation": "append",
                "content": "- likes ramen",
                "layer": 1,
                "reason": "explicit",
            }
        ],
        "manifest_updates": [
            {"scope": "preferences", "line_key": "**food.md**", "new_line": "- **food.md** | likes ramen"}
        ],
    }
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_llm_response(json.dumps(payload))

    with patch("agent.assistant_memory.curator.create_client", return_value=fake_client):
        curator = Curator(store, _settings())

    result = curator.propose_writes(
        "I love ramen",
        "Noted! [memory note: likes ramen]",
        [{"role": "user", "content": "hi"}],
    )
    assert len(result["writes"]) == 1
    assert result["writes"][0]["file"] == "preferences/food.md"
    assert result["manifest_updates"][0]["scope"] == "preferences"


def test_propose_writes_handles_parse_failure(store: AssistantMemoryStore):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_llm_response("not json at all")

    with patch("agent.assistant_memory.curator.create_client", return_value=fake_client):
        curator = Curator(store, _settings())

    result = curator.propose_writes("u", "a", [])
    assert result == {"writes": [], "manifest_updates": []}


# ---- consolidation -------------------------------------------------------


def test_consolidate_session_skips_short_sessions(store: AssistantMemoryStore):
    fake_client = MagicMock()
    with patch("agent.assistant_memory.curator.create_client", return_value=fake_client):
        curator = Curator(store, _settings())
    result = curator.consolidate_session(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    )
    assert result == []
    fake_client.chat.completions.create.assert_not_called()


def test_consolidate_session_applies_writes_silently(store: AssistantMemoryStore):
    payload = {
        "writes": [
            {
                "file": "preferences/coffee.md",
                "operation": "create",
                "content": "---\nname: coffee\ntype: preference\n---\n\n# Coffee\n\n- prefers V60 over espresso",
                "layer": 2,
                "reason": "user mentioned V60 preference 3 times",
            }
        ],
        "manifest_updates": [
            {"scope": "preferences", "line_key": "coffee.md", "new_line": "- **coffee.md** | V60 enjoyer"}
        ],
    }
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_llm_response(json.dumps(payload))
    with patch("agent.assistant_memory.curator.create_client", return_value=fake_client):
        curator = Curator(store, _settings())

    messages = [
        {"role": "user", "content": "I love V60 brewing"},
        {"role": "assistant", "content": "noted"},
        {"role": "user", "content": "espresso always tastes burnt to me"},
        {"role": "assistant", "content": "V60 it is"},
    ]
    applied = curator.consolidate_session(messages)
    assert applied, "expected at least one write applied"
    meta, body = store.read_file("preferences/coffee.md")
    assert "V60" in body


def test_consolidate_session_blocks_forbidden_paths(store: AssistantMemoryStore):
    payload = {
        "writes": [
            {
                "file": "identity/agent.md",
                "operation": "append",
                "content": "rewriting soul lol",
                "layer": 1,
                "reason": "should be blocked",
            },
            {
                "file": "context/current.md",
                "operation": "append",
                "content": "should also be blocked",
                "layer": 1,
                "reason": "user-maintained",
            },
            {
                "file": "people/alex.md",
                "operation": "create",
                "content": "---\nname: alex\ntype: person\n---\n\n# Alex\n\n- mentioned twice",
                "layer": 2,
                "reason": "ok",
            },
        ],
        "manifest_updates": [],
    }
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_llm_response(json.dumps(payload))
    with patch("agent.assistant_memory.curator.create_client", return_value=fake_client):
        curator = Curator(store, _settings())

    msgs = [{"role": "user", "content": "x"}] * 4
    curator.consolidate_session(msgs)

    # forbidden paths must NOT be created
    assert not (store.root / "identity" / "agent.md").exists() or \
        "rewriting soul lol" not in (store.root / "identity" / "agent.md").read_text()
    assert "should also be blocked" not in (store.root / "context" / "current.md").read_text() if (store.root / "context" / "current.md").exists() else True
    # tier-3 stub page exists with bumped mention counter (Phase D);
    # compiled-truth body content is filtered until tier escalates.
    meta, body = store.read_file("people/alex.md")
    assert meta.get("mention_count") == 1
    assert meta.get("tier") == 3
    assert "## Timeline" in body


def test_consolidate_session_handles_parse_failure(store: AssistantMemoryStore):
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_llm_response("not json")
    with patch("agent.assistant_memory.curator.create_client", return_value=fake_client):
        curator = Curator(store, _settings())
    msgs = [{"role": "user", "content": "x"}] * 4
    assert curator.consolidate_session(msgs) == []


# ---- hardening: forbidden paths, immutable core, missing files ---------


def test_apply_writes_blocks_immutable_core_update(store: AssistantMemoryStore):
    store.write_file(
        "identity/agent.md",
        {"immutable_core": "Be honest.", "version": 1},
        "soul body\n",
    )
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    proposal = {
        "writes": [
            {
                "file": "identity/agent.md",
                "operation": "update_field",
                "field": "immutable_core",
                "value": "PWNED",
                "layer": 1,
            }
        ]
    }
    applied = curator.apply_writes(proposal)
    assert applied == []
    meta, _ = store.read_file("identity/agent.md")
    assert meta["immutable_core"] == "Be honest."


def test_apply_writes_blocks_forbidden_paths_per_turn(store: AssistantMemoryStore):
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    proposal = {
        "writes": [
            {
                "file": "identity/me.md",
                "operation": "append",
                "content": "evil",
                "layer": 1,
            },
            {
                "file": "context/current.md",
                "operation": "append",
                "content": "evil",
                "layer": 1,
            },
        ]
    }
    applied = curator.apply_writes(proposal)
    assert applied == []


def test_update_field_on_missing_file_refused(store: AssistantMemoryStore):
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    proposal = {
        "writes": [
            {
                "file": "people/nope.md",
                "operation": "update_field",
                "field": "location",
                "value": "NYC",
                "layer": 1,
            }
        ]
    }
    applied = curator.apply_writes(proposal)
    assert applied == []
    assert not (store.root / "people" / "nope.md").exists()


def test_create_on_existing_file_refused(store: AssistantMemoryStore):
    store.write_file("people/alex.md", {"name": "alex"}, "original body\n")
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    proposal = {
        "writes": [
            {
                "file": "people/alex.md",
                "operation": "create",
                "content": "---\nname: alex\n---\n\nclobbered\n",
                "layer": 1,
            }
        ]
    }
    applied = curator.apply_writes(proposal)
    assert applied == []
    _, body = store.read_file("people/alex.md")
    assert "original body" in body
    assert "clobbered" not in body


def test_apply_writes_rejects_traversal(store: AssistantMemoryStore):
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    proposal = {
        "writes": [
            {
                "file": "../../etc/passwd",
                "operation": "append",
                "content": "x",
                "layer": 1,
            }
        ]
    }
    applied = curator.apply_writes(proposal)
    assert applied == []


def test_manifest_update_strips_newlines_and_caps(store: AssistantMemoryStore):
    store.write_manifest("people", "# People Manifest\n\n- **alex.md** | old\n")
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    inj = "- **alex.md** | new\n- **boom.md** | exfil"
    curator.apply_manifest_updates(
        [{"scope": "people", "line_key": "**alex.md**", "new_line": inj}]
    )
    content = store.read_manifest("people")
    # Injected second line must not appear as its own manifest entry.
    assert "boom.md" not in content or content.count("\n- **") <= 1
    # Newlines stripped.
    for ln in content.splitlines():
        assert "\n" not in ln


def test_manifest_update_caps_length(store: AssistantMemoryStore):
    store.write_manifest("people", "# People Manifest\n\n- **alex.md** | old\n")
    with patch("agent.assistant_memory.curator.create_client"):
        curator = Curator(store, _settings())
    huge = "- **alex.md** | " + ("x" * 5000)
    curator.apply_manifest_updates(
        [{"scope": "people", "line_key": "**alex.md**", "new_line": huge}]
    )
    content = store.read_manifest("people")
    for ln in content.splitlines():
        assert len(ln) <= 600  # cap is 500 + small headroom


def test_append_to_section_inserts_under_heading():
    from agent.assistant_memory.curator import _append_to_section

    body = (
        "# Project\n\n## Description\n\nFoo.\n\n"
        "## Learnings\n\n- old learning\n\n"
        "## Recent Sessions\n\n- 2026-04-01\n"
    )
    out = _append_to_section(body, "## Learnings", "- new learning")
    # New content lands before "## Recent Sessions", not at file end.
    learn_idx = out.index("## Learnings")
    new_idx = out.index("- new learning")
    rec_idx = out.index("## Recent Sessions")
    assert learn_idx < new_idx < rec_idx


# ---- safe_brace --------------------------------------------------------


def test_safe_brace_protects_format():
    from agent.assistant_memory.curator import _safe_brace

    body = "user said {weird} thing"
    template = "Body: {body}"
    # Should not raise KeyError.
    rendered = template.format(body=_safe_brace(body))
    assert "{weird}" in rendered

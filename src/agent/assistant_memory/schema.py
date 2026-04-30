"""Dataclasses and YAML frontmatter helpers for the assistant memory store."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


MEMORY_DIR_DEFAULT = "~/assistant-memory"


def get_memory_dir() -> Path:
    """Return the configured memory dir, expanding ~."""
    raw = os.environ.get("ASSISTANT_MEMORY_DIR") or MEMORY_DIR_DEFAULT
    return Path(raw).expanduser()


def _split_fences(text: str) -> tuple[str, str] | None:
    """Locate the YAML frontmatter block.

    Returns (yaml_block, body) where yaml_block is the text between the
    opening and closing ``---`` lines, or ``None`` when the file does not
    open with a frontmatter fence. The closing fence is the first subsequent
    line whose stripped value is exactly ``---`` for which the resulting YAML
    parses as a mapping. This handles multi-line block scalars (``|``/``>``)
    that themselves contain a literal ``---`` line.
    """
    if not text.startswith("---"):
        return None
    # Require the first line to be exactly --- (allow trailing whitespace).
    first_nl = text.find("\n")
    if first_nl == -1:
        return None
    if text[:first_nl].strip() != "---":
        return None

    rest = text[first_nl + 1 :]
    lines = rest.split("\n")

    # Collect every candidate line index whose stripped value is "---".
    candidates: list[int] = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
    if not candidates:
        return None

    # Prefer the latest valid fence: a `|`/`>` block scalar that contains a
    # literal `---` line will still parse if we stop early, but we'd lose
    # subsequent top-level keys. Walking from the last candidate backwards
    # picks the widest YAML window that still parses as a mapping.
    for idx in reversed(candidates):
        yaml_block = "\n".join(lines[:idx])
        try:
            loaded = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
        except yaml.YAMLError:
            continue
        if isinstance(loaded, dict):
            body = "\n".join(lines[idx + 1 :])
            # Strip a single leading newline — historical behavior.
            if body.startswith("\n"):
                body = body[1:]
            return yaml_block, body

    return None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from a markdown body.

    Returns (meta_dict, body_str). If no frontmatter is present or the YAML
    is malformed, meta is empty and the full text is returned as the body.
    """
    if not text:
        return {}, text
    split = _split_fences(text)
    if split is None:
        return {}, text
    yaml_block, body = split
    try:
        loaded = yaml.safe_load(yaml_block) if yaml_block.strip() else {}
    except yaml.YAMLError as exc:
        logger.warning("malformed frontmatter; treating as body-only: %s", exc)
        return {}, text
    if not isinstance(loaded, dict):
        return {}, text
    return loaded, body


def dump_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Serialize meta + body into a frontmatter markdown string.

    Multi-line string values are emitted as ``|`` block scalars so that
    immutable_core and similar fields round-trip cleanly.
    """
    if not meta:
        return body
    meta_yaml = yaml.safe_dump(
        meta,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    ).strip()
    return f"---\n{meta_yaml}\n---\n\n{body}" if body else f"---\n{meta_yaml}\n---\n"


# ---- shared model picker -------------------------------------------------


def pick_model(settings: Any, prefer: str = "pro") -> str:
    """Resolve a model name with consistent fallback to ``settings.model``.

    ``prefer`` may be ``"pro"`` or ``"flash"``. Empty strings on the preferred
    field fall through to the legacy ``model`` field.
    """
    if prefer == "flash":
        primary = getattr(settings, "model_flash", "") or ""
    else:
        primary = getattr(settings, "model_pro", "") or ""
    if primary:
        return primary
    return getattr(settings, "model", "") or ""


# ---- dataclasses ---------------------------------------------------------


@dataclass
class PersonFile:
    name: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""


@dataclass
class ProjectFile:
    project_id: str
    cwd: str = ""
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    last_summarized_session: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""


@dataclass
class PreferenceFile:
    topic: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""


@dataclass
class LogEntry:
    date: str
    body: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityFile:
    immutable_core: str = ""
    soul: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Manifest:
    scope: str
    content: str = ""


@dataclass
class RetrievalResult:
    scopes: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    reasoning: str = ""

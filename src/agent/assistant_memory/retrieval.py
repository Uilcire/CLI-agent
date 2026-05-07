"""Two-stage LLM retrieval pipeline for assistant memory."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.config.settings import Settings
from agent.llm.client import create_client

from .prompts import STAGE1_SCOPE_PROMPT, STAGE2_FILE_PROMPT
from .schema import RetrievalResult, parse_frontmatter, pick_model
from .store import SCOPES, AssistantMemoryStore


logger = logging.getLogger(__name__)


_ALL_SCOPES_FOR_RETRIEVAL: tuple[str, ...] = tuple(s for s in SCOPES if s != "context")
_MAX_FILES = 5
_MAX_RECENT_TURNS = 3


def _safe_brace(s: Any) -> str:
    """Escape ``{``/``}`` so untrusted content survives ``str.format``."""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("{", "{{").replace("}", "}}")


def _format_recent_turns(recent_turns: list[dict]) -> str:
    if not recent_turns:
        return "(none)"
    tail = recent_turns[-_MAX_RECENT_TURNS:]
    lines: list[str] = []
    for turn in tail:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
        else:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


class RetrievalPipeline:
    def __init__(self, store: AssistantMemoryStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.client = create_client(settings)
        self.model_flash = pick_model(settings, prefer="flash")

    def _call_flash_json(self, prompt: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model_flash,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        return json.loads(content)

    def select_scopes(self, query: str, recent_turns: list[dict]) -> RetrievalResult:
        index_md = self.store.read_index()
        prompt = STAGE1_SCOPE_PROMPT.format(
            recent_turns=_safe_brace(_format_recent_turns(recent_turns)),
            index_md=_safe_brace(index_md or "(empty)"),
            user_query=_safe_brace(query),
        )
        try:
            data = self._call_flash_json(prompt)
            scopes = data.get("scopes", [])
            if not isinstance(scopes, list):
                raise ValueError("scopes is not a list")
            scopes = [s for s in scopes if isinstance(s, str)]
            reasoning = data.get("reasoning", "")
            if not isinstance(reasoning, str):
                reasoning = ""
            logger.info("Stage 1 scopes: %s | reason: %s", scopes, reasoning[:120])
            return RetrievalResult(scopes=scopes, reasoning=reasoning)
        except (json.JSONDecodeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("Stage 1 scope selection parse failed: %s; defaulting to all scopes", exc)
            return RetrievalResult(
                scopes=list(_ALL_SCOPES_FOR_RETRIEVAL),
                reasoning="fallback: stage 1 parse failed",
            )

    def select_files(
        self,
        query: str,
        recent_turns: list[dict],
        scopes: list[str],
        hints: list[str] | None = None,
    ) -> list[str]:
        if not scopes:
            return []
        manifest_chunks: list[str] = []
        for scope in scopes:
            content = self.store.read_manifest(scope)
            if not content:
                continue
            manifest_chunks.append(f"=== {scope}/_manifest.md ===\n{content}")
        manifests = "\n\n".join(manifest_chunks) if manifest_chunks else "(no manifests)"
        prompt = STAGE2_FILE_PROMPT.format(
            recent_turns=_safe_brace(_format_recent_turns(recent_turns)),
            manifests=_safe_brace(manifests),
            user_query=_safe_brace(query),
        )
        # Sanitize hints before injecting into the prompt: a malicious slug
        # like "alex\n\n# OVERRIDE..." could otherwise pivot the Stage 2 model.
        clean_hints: list[str] = []
        for h in hints or []:
            if not isinstance(h, str):
                continue
            flat = h.replace("\n", " ").replace("\r", " ").strip()[:80]
            if flat:
                clean_hints.append(flat)
        if clean_hints:
            prompt += (
                "\n\n# Hints from signal detector\n"
                "These slugs/entities were extracted from the user's latest message. "
                "Weigh files matching them more heavily.\n"
                + ", ".join(clean_hints[:20])
                + "\n"
            )
        try:
            data = self._call_flash_json(prompt)
            files = data.get("files", [])
            if not isinstance(files, list):
                raise ValueError("files is not a list")
            cleaned = [f for f in files if isinstance(f, str) and f][:_MAX_FILES]
            logger.info("Stage 2 files: %s", cleaned)
            return cleaned
        except (json.JSONDecodeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("Stage 2 file selection parse failed: %s; returning empty list", exc)
            return []

    def retrieve(
        self,
        query: str,
        recent_turns: list[dict],
        hints: list[str] | None = None,
    ) -> dict[str, Any]:
        stage1 = self.select_scopes(query, recent_turns)
        files = self.select_files(query, recent_turns, stage1.scopes, hints=hints)
        file_contents: dict[str, str] = {}
        for rel_path in files:
            _, body = self.store.read_file(rel_path)
            file_contents[rel_path] = body

        index_meta, _ = parse_frontmatter(self.store.read_index())
        user_summary = index_meta.get("user_summary", "")
        if not isinstance(user_summary, str):
            user_summary = ""

        return {
            "files": files,
            "current_context": self.store.read_current_context(),
            "user_summary": user_summary,
            "agent_soul": self.store.read_agent_soul(),
            "immutable_core": self.store.read_immutable_core(),
            "file_contents": file_contents,
        }

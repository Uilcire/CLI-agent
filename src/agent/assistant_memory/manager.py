"""AssistantMemoryManager — replaces the old MemoryManager facade.

Public interface mirrors the old `agent.memory.manager.MemoryManager` so
`cli/app.py` (and any other callers) keep working unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.config.settings import Settings

from .curator import Curator, rebuild_manifest
from .retrieval import RetrievalPipeline
from .schema import parse_frontmatter
from .store import SCOPES, AssistantMemoryStore


logger = logging.getLogger(__name__)

_RECENT_TURN_CAP = 6  # 3 user + 3 assistant


@dataclass
class ProjectView:
    """Lightweight view of a project file for cli/app.py consumers."""

    project_id: str
    description: str = ""
    cwd: str = ""
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)


# Back-compat alias — old name retained one release for external imports.
MigratedProjectView = ProjectView


def _cwd_project_id(cwd: str) -> str:
    abs_cwd = os.path.abspath(cwd)
    return hashlib.sha256(abs_cwd.encode()).hexdigest()[:12]


def _slugify(text: str, max_len: int = 40) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s:
        return f"project-{int(time.time())}"
    return s[:max_len].rstrip("-") or f"project-{int(time.time())}"


def _project_view_from_file(meta: dict[str, Any], body: str, project_id: str) -> ProjectView:
    description = ""
    # Pull description from "## Description" section.
    desc_match = re.search(r"##\s*Description\s*\n+([^\n#].*?)(?:\n##|\Z)", body, re.DOTALL)
    if desc_match:
        description = desc_match.group(1).strip().splitlines()[0].strip() if desc_match.group(1).strip() else ""
    if not description:
        description = str(meta.get("description") or project_id)
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    caps = meta.get("capabilities") or []
    if not isinstance(caps, list):
        caps = []
    return ProjectView(
        project_id=str(meta.get("project_id") or project_id),
        description=description,
        cwd=str(meta.get("cwd") or ""),
        status=str(meta.get("status") or "active"),
        tags=[str(t) for t in tags],
        capabilities=[str(c) for c in caps],
    )


class AssistantMemoryManager:
    """Replaces the old MemoryManager. Same public surface; new internals."""

    def __init__(self, data_dir: str, settings: Settings) -> None:
        self.data_dir = data_dir
        self.settings = settings
        self.store = AssistantMemoryStore(Path(data_dir))
        self.retrieval = RetrievalPipeline(self.store, settings)
        self.curator = Curator(self.store, settings)
        self.recent_turns: list[dict] = []
        self._active_session_messages: list[dict] = []
        self.project_id: str | None = None
        self._last_curator_thread: threading.Thread | None = None

    # ---- lifecycle -------------------------------------------------------

    def on_startup(self, project_id: str | None = None) -> str:
        try:
            self.project_id = project_id
            self.recent_turns = []
            self._active_session_messages = []

            immutable_core = self.store.read_immutable_core()
            soul = self.store.read_agent_soul()

            index_meta, _ = parse_frontmatter(self.store.read_index())
            user_summary = index_meta.get("user_summary", "")
            if not isinstance(user_summary, str):
                user_summary = ""

            current_context = self.store.read_current_context()

            parts: list[str] = []
            if immutable_core.strip():
                parts.append(f"# Agent Immutable Core\n\n{immutable_core.strip()}")
            if soul.strip():
                parts.append(f"# Agent Soul\n\n{soul.strip()}")
            if user_summary.strip():
                parts.append(f"# User\n\n{user_summary.strip()}")
            if current_context.strip():
                parts.append(f"# Current context\n\n{current_context.strip()}")
            return "\n\n".join(parts)
        except Exception as exc:
            logger.exception("AssistantMemoryManager.on_startup failed: %s", exc)
            return ""

    def retrieve_for_query(self, query: str) -> str:
        """Run two-stage retrieval and format a markdown block for system-prompt injection.

        Returns ``""`` when retrieval yields nothing or fails.
        """
        try:
            result = self.retrieval.retrieve(query, list(self.recent_turns))
        except Exception as exc:
            logger.warning("retrieve_for_query failed: %s", exc)
            return ""

        try:
            files: list[str] = result.get("files", []) or []
            file_contents: dict[str, str] = result.get("file_contents", {}) or {}
            current_context = result.get("current_context", "") or ""
            user_summary = result.get("user_summary", "") or ""

            sections: list[str] = []
            for rel in files:
                body = file_contents.get(rel, "")
                if not body.strip():
                    continue
                sections.append(f"=== {rel} ===\n{body.strip()}")
            if current_context.strip():
                sections.append(f"=== context/current.md ===\n{current_context.strip()}")

            if not sections and not user_summary.strip():
                return ""

            header_lines = ["# Retrieved memories"]
            if user_summary.strip():
                # _index.md user_summary one-liner reference.
                header_lines.append(f"<!-- _index.md user_summary: {user_summary.strip()} -->")

            return "\n\n".join(header_lines + sections)
        except Exception as exc:
            logger.warning("retrieve_for_query format failed: %s", exc)
            return ""

    def on_user_turn(self, content: str) -> None:
        try:
            entry = {"role": "user", "content": content}
            self.recent_turns.append(entry)
            if len(self.recent_turns) > _RECENT_TURN_CAP:
                self.recent_turns = self.recent_turns[-_RECENT_TURN_CAP:]
            self._active_session_messages.append(entry)
        except Exception as exc:
            logger.warning("on_user_turn failed: %s", exc)

    def on_assistant_turn(self, content: str) -> None:
        try:
            entry = {"role": "assistant", "content": content}
            self.recent_turns.append(entry)
            if len(self.recent_turns) > _RECENT_TURN_CAP:
                self.recent_turns = self.recent_turns[-_RECENT_TURN_CAP:]
            self._active_session_messages.append(entry)
        except Exception as exc:
            logger.warning("on_assistant_turn append failed: %s", exc)
            return

        # Last user message is the most recent role=user turn.
        last_user = ""
        for t in reversed(self.recent_turns[:-1]):
            if t.get("role") == "user":
                last_user = t.get("content", "")
                break

        recent_snapshot = list(self.recent_turns)
        curator = self.curator

        def _run_curator() -> None:
            try:
                proposal = curator.propose_writes(last_user, content, recent_snapshot)
                curator.apply_writes(proposal, confirm_callback=None)
                curator.apply_manifest_updates(proposal.get("manifest_updates", []))
            except Exception as exc:
                logger.warning("curator post-turn failed: %s", exc)

        t = threading.Thread(target=_run_curator, daemon=True)
        t.start()
        self._last_curator_thread = t

    def on_exit(self) -> str | None:
        try:
            if not self._active_session_messages:
                return None
            # Wait briefly for the most recent per-turn curator to finish so
            # consolidation reads a fresh manifest. Bounded — don't hang exit.
            if self._last_curator_thread is not None:
                try:
                    self._last_curator_thread.join(timeout=2.0)
                except Exception as exc:
                    logger.warning("curator thread join failed: %s", exc)
            messages = list(self._active_session_messages)
            project_id = self.project_id
            curator = self.curator

            def _run() -> None:
                try:
                    curator.consolidate_session(messages)
                except Exception as exc:
                    logger.warning("consolidation pass failed: %s", exc)
                try:
                    curator.summarize_session(messages, project_id)
                except Exception as exc:
                    logger.warning("background session digest failed: %s", exc)

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            return "Dreaming... (consolidating + digesting in background)"
        except Exception as exc:
            logger.exception("on_exit failed: %s", exc)
            return f"Session ended (error: {exc})."

    # ---- project lookup --------------------------------------------------

    def find_project_for_cwd(self, cwd: str) -> ProjectView | None:
        try:
            pid = _cwd_project_id(cwd)
            rel = f"projects/{pid}.md"
            full_path = Path(self.data_dir) / rel
            if not full_path.exists():
                return None
            meta, body = self.store.read_file(rel)
            if not meta and not body:
                return None
            return _project_view_from_file(meta, body, pid)
        except Exception as exc:
            logger.warning("find_project_for_cwd failed: %s", exc)
            return None

    def onboard_for_cwd(self, cwd: str, print_fn=print) -> ProjectView | None:
        try:
            existing = self.find_project_for_cwd(cwd)
            if existing is not None:
                return existing
            pid = _cwd_project_id(cwd)
            abs_cwd = os.path.abspath(cwd)
            description = os.path.basename(abs_cwd) or pid
            meta = {
                "project_id": pid,
                "cwd": abs_cwd,
                "status": "active",
                "tags": [],
                "capabilities": [],
                "last_summarized_session": None,
            }
            body = f"# {description}\n\n## Description\n\n{description}\n\n## Learnings\n\n"
            self.store.write_file(f"projects/{pid}.md", meta, body)
            self._append_manifest_line("projects", pid, abs_cwd, description)
            print_fn(f"Created new project: {description} [{pid}]")
            return _project_view_from_file(meta, body, pid)
        except Exception as exc:
            logger.exception("onboard_for_cwd failed: %s", exc)
            print_fn(f"Project setup failed: {exc}. Starting without project context.")
            return None

    def onboard(self, description: str) -> ProjectView | None:
        try:
            slug = _slugify(description)
            rel = f"projects/{slug}.md"
            # Avoid clobber: if exists, suffix with timestamp.
            if (Path(self.data_dir) / rel).exists():
                slug = f"{slug}-{int(time.time())}"
                rel = f"projects/{slug}.md"
            meta = {
                "project_id": slug,
                "cwd": "",
                "status": "active",
                "tags": [],
                "capabilities": [],
                "last_summarized_session": None,
            }
            body = f"# {slug}\n\n## Description\n\n{description.strip()}\n\n## Learnings\n\n"
            self.store.write_file(rel, meta, body)
            self._append_manifest_line("projects", slug, "", description)
            return _project_view_from_file(meta, body, slug)
        except Exception as exc:
            logger.exception("onboard failed: %s", exc)
            return None

    def _append_manifest_line(self, scope: str, project_id: str, cwd: str, description: str) -> None:
        try:
            current = self.store.read_manifest(scope)
            new_line = (
                f"- **{project_id}.md** | active | {description} | "
                f"cwd:{cwd or '(none)'} | tags: "
            )
            if not current:
                content = f"# {scope.title()} Manifest\n\n{new_line}\n"
            else:
                # Replace if line_key already present.
                lines = current.splitlines()
                key = f"**{project_id}.md**"
                replaced = False
                for i, line in enumerate(lines):
                    if key in line:
                        lines[i] = new_line
                        replaced = True
                        break
                if not replaced:
                    lines.append(new_line)
                content = "\n".join(lines)
                if not content.endswith("\n"):
                    content += "\n"
            self.store.write_manifest(scope, content)
        except Exception as exc:
            logger.warning("manifest append failed: %s", exc)

    # ---- slash commands --------------------------------------------------

    def handle_command(self, cmd: str) -> str | None:
        if not cmd or not cmd.startswith("/memory"):
            return None
        try:
            parts = cmd.strip().split(maxsplit=2)
            # parts[0] == "/memory"
            if len(parts) == 1 or (len(parts) == 2 and parts[1] == "help"):
                return (
                    "Memory commands:\n"
                    "  /memory list <scope>          — list files in scope\n"
                    "  /memory show <scope>/<file>   — print a file's contents\n"
                    "  /memory rebuild <scope>       — rebuild a scope manifest\n"
                    "  /memory current               — show context/current.md\n"
                    f"  scopes: {', '.join(SCOPES)}"
                )

            sub = parts[1]
            arg = parts[2] if len(parts) >= 3 else ""

            if sub == "list":
                if not arg:
                    return "Usage: /memory list <scope>"
                if arg not in SCOPES:
                    return f"Unknown scope: {arg}. Choose from: {', '.join(SCOPES)}"
                files = self.store.list_files(arg)
                return "\n".join(files) if files else f"(no files in {arg}/)"

            if sub == "show":
                if not arg:
                    return "Usage: /memory show <scope>/<file>"
                meta, body = self.store.read_file(arg)
                if not meta and not body:
                    return f"File not found: {arg}"
                from .schema import dump_frontmatter
                return dump_frontmatter(meta, body) if meta else body

            if sub == "rebuild":
                if not arg or arg not in SCOPES:
                    return f"Usage: /memory rebuild <scope>. Scopes: {', '.join(SCOPES)}"
                content = rebuild_manifest(self.store, arg, self.settings)
                self.store.write_manifest(arg, content)
                return f"Rebuilt {arg}/_manifest.md"

            if sub == "current":
                body = self.store.read_current_context()
                return body if body.strip() else "(context/current.md is empty)"

            return f"Unknown memory subcommand: {sub}. Try /memory help."
        except Exception as exc:
            logger.exception("handle_command failed: %s", exc)
            return f"Memory command failed: {exc}"

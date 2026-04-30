"""Filesystem-backed store for assistant memory markdown files."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from .schema import dump_frontmatter, parse_frontmatter


logger = logging.getLogger(__name__)


SCOPES: tuple[str, ...] = ("identity", "people", "preferences", "projects", "context", "log")


class AssistantMemoryStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        for scope in SCOPES:
            (self.root / scope).mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sweep_tmp_files()

    # ---- safety ----------------------------------------------------------

    def _safe_rel(self, rel_path: str) -> Path:
        """Validate ``rel_path`` and return its absolute, root-contained Path.

        Rejects: empty strings, absolute paths, NUL bytes, ``..`` segments,
        and any path that escapes ``self.root`` after resolution.
        """
        if not isinstance(rel_path, str) or not rel_path:
            raise ValueError("rel_path must be a non-empty string")
        if "\x00" in rel_path:
            raise ValueError("rel_path contains NUL byte")
        if rel_path.startswith("/") or rel_path.startswith("\\"):
            raise ValueError(f"rel_path must be relative: {rel_path!r}")
        # Drive-letter / windows-style absolutes.
        if len(rel_path) >= 2 and rel_path[1] == ":":
            raise ValueError(f"rel_path must be relative: {rel_path!r}")

        normalized = os.path.normpath(rel_path)
        if normalized.startswith("..") or normalized == "." or normalized == "":
            raise ValueError(f"rel_path escapes root: {rel_path!r}")
        # After normpath, any remaining .. segment is an escape attempt.
        parts = normalized.replace("\\", "/").split("/")
        if any(p == ".." for p in parts):
            raise ValueError(f"rel_path contains '..': {rel_path!r}")

        candidate = (self.root / normalized).resolve()
        root_resolved = self.root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"rel_path escapes root: {rel_path!r}") from exc
        return candidate

    def _sweep_tmp_files(self) -> None:
        try:
            for tmp in self.root.rglob("*.tmp"):
                try:
                    tmp.unlink()
                except OSError as exc:
                    logger.warning("failed to remove stale tmp %s: %s", tmp, exc)
        except OSError as exc:
            logger.warning("tmp sweep failed: %s", exc)

    # ---- atomic IO -------------------------------------------------------

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ---- file IO ---------------------------------------------------------

    def read_file(self, rel_path: str) -> tuple[dict[str, Any], str]:
        path = self._safe_rel(rel_path)
        with self._lock:
            if not path.exists():
                return {}, ""
            return parse_frontmatter(path.read_text(encoding="utf-8"))

    def write_file(self, rel_path: str, meta: dict[str, Any], body: str) -> None:
        path = self._safe_rel(rel_path)
        with self._lock:
            self._atomic_write(path, dump_frontmatter(meta, body))

    def read_manifest(self, scope: str) -> str:
        path = self._safe_rel(f"{scope}/_manifest.md")
        with self._lock:
            return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_manifest(self, scope: str, content: str) -> None:
        path = self._safe_rel(f"{scope}/_manifest.md")
        with self._lock:
            self._atomic_write(path, content)

    def read_index(self) -> str:
        path = self._safe_rel("_index.md")
        with self._lock:
            return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_index(self, content: str) -> None:
        path = self._safe_rel("_index.md")
        with self._lock:
            self._atomic_write(path, content)

    def list_files(self, scope: str) -> list[str]:
        scope_dir = self._safe_rel(scope)
        if not scope_dir.is_dir():
            return []
        out: list[str] = []
        for path in sorted(scope_dir.rglob("*.md")):
            if path.name == "_manifest.md":
                continue
            if path.suffix == ".tmp" or path.name.endswith(".tmp"):
                continue
            out.append(str(path.relative_to(self.root)))
        return out

    def read_current_context(self) -> str:
        _, body = self.read_file("context/current.md")
        return body

    def read_immutable_core(self) -> str:
        meta, _ = self.read_file("identity/agent.md")
        value = meta.get("immutable_core", "")
        return value if isinstance(value, str) else ""

    def read_agent_soul(self) -> str:
        _, body = self.read_file("identity/agent.md")
        return body

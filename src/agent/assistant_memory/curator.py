"""Curator (write side) for the assistant memory system."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable

from agent.config.settings import Settings
from agent.llm.client import create_client

from .page import (
    append_timeline,
    format_sourced_bullet,
    join_layers,
    rewrite_compiled,
    split_layers,
)
from .prompts import CONSOLIDATION_PROMPT, CURATOR_PROMPT
from .schema import dump_frontmatter, parse_frontmatter, pick_model
from .store import SCOPES, AssistantMemoryStore
from .templates import (
    LIFE_DOMAIN_TEMPLATE,
    PERSON_TEMPLATE,
    PREFERENCE_TEMPLATE,
    THREAD_TEMPLATE,
    render_template,
)
from .tiers import (
    people_slug_from_path,
    record_mention,
    update_people_manifest_line,
)


logger = logging.getLogger(__name__)


_MEMORY_NOTE_RE = re.compile(r"\[memory note:\s*(.*?)\]", re.IGNORECASE | re.DOTALL)

_CORRECTION_RE = re.compile(
    r"\b(no,|nope|actually|correction|that's wrong|that is wrong|not\b)",
    re.IGNORECASE,
)

_TEMPLATE_BY_SCOPE: dict[str, str] = {
    "people": PERSON_TEMPLATE,
    "life": LIFE_DOMAIN_TEMPLATE,
    "threads": THREAD_TEMPLATE,
    "preferences": PREFERENCE_TEMPLATE,
}


def _scope_of(rel: str) -> str:
    return rel.split("/", 1)[0] if "/" in rel else ""


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _detect_correction(text: str) -> bool:
    return bool(_CORRECTION_RE.search(text or ""))


def _wrap_state_bullets(
    content: str,
    source_type: str,
    confidence: str | None,
    date: str | None,
) -> str:
    """Re-tag any plain bullet line in ``content`` with a sourcing marker.

    Lines already carrying ``_[...]_`` are left alone. Non-bullet lines pass
    through unchanged. Used when content lands in a State section.
    """
    if not content:
        return content
    out: list[str] = []
    for raw in content.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            out.append(raw)
            continue
        if "_[" in stripped and stripped.rstrip().endswith("]_"):
            out.append(raw)
            continue
        text = stripped[2:].strip()
        if not text:
            out.append(raw)
            continue
        try:
            tagged = format_sourced_bullet(text, source_type, date=date, confidence=confidence)
        except ValueError:
            out.append(raw)
            continue
        indent = line[: len(line) - len(stripped)]
        out.append(f"{indent}{tagged}")
    return "\n".join(out)


_FORBIDDEN_PATHS: tuple[str, ...] = (
    "identity/agent.md",
    "identity/me.md",
    "context/current.md",
)

_MANIFEST_LINE_MAX = 500


def _safe_brace(s: Any) -> str:
    """Escape ``{``/``}`` so untrusted content survives ``str.format``."""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("{", "{{").replace("}", "}}")


def _is_forbidden(rel: str) -> bool:
    if not isinstance(rel, str) or not rel:
        return False
    try:
        normalized = os.path.normpath(rel).replace("\\", "/").lower()
    except (TypeError, ValueError):
        return False
    return normalized in _FORBIDDEN_PATHS


def extract_memory_notes(assistant_text: str) -> list[str]:
    """Return the content of every `[memory note: ...]` marker in order."""
    return [m.group(1).strip() for m in _MEMORY_NOTE_RE.finditer(assistant_text or "")]


def strip_memory_notes(assistant_text: str) -> str:
    """Remove `[memory note: ...]` markers from text; collapse leftover whitespace."""
    if not assistant_text:
        return assistant_text
    cleaned = _MEMORY_NOTE_RE.sub("", assistant_text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object parse — accepts fenced or bare JSON."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```$", "", stripped)
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


class Curator:
    """Post-turn curator that proposes and applies memory writes."""

    _FORBIDDEN_PATHS = _FORBIDDEN_PATHS  # backwards-compat reference
    _CONSOLIDATION_MIN_TURNS = 4

    def __init__(self, store: AssistantMemoryStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.client = create_client(settings)
        self.model = pick_model(settings, prefer="pro")
        self._last_user_msg: str = ""

    # ---- proposal --------------------------------------------------------

    def propose_writes(
        self,
        user_msg: str,
        assistant_msg: str,
        recent_turns: list[dict],
        signals: dict | None = None,
    ) -> dict:
        """Ask the curator LLM what to write. Always returns a dict with both keys.

        ``signals`` is the signal-detector output. When non-empty it is appended
        to the prompt so the curator LLM doesn't re-discover what was already
        extracted on the user-side pass.
        """
        self._last_user_msg = user_msg or ""
        recent_str = _format_turns(recent_turns)
        prompt = (
            CURATOR_PROMPT
            + "\n\n# Recent turns\n"
            + recent_str
            + "\n\n# Last user message\n"
            + (user_msg or "")
            + "\n\n# Last assistant message\n"
            + (assistant_msg or "")
        )
        if isinstance(signals, dict) and any(signals.get(k) for k in signals):
            try:
                signals_json = json.dumps(signals, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                signals_json = ""
            if signals_json:
                prompt += (
                    "\n\n# Signals already detected from user message\n"
                    "(Pre-extracted by the signal detector — use as a starting point, "
                    "do not re-discover.)\n"
                    + signals_json
                )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - network/client errors
            logger.warning("curator LLM call failed: %s", exc)
            return {"writes": [], "manifest_updates": []}

        parsed = _parse_json_object(content)
        if parsed is None:
            logger.warning("curator returned non-JSON content; ignoring")
            return {"writes": [], "manifest_updates": []}

        writes = parsed.get("writes") or []
        manifest_updates = parsed.get("manifest_updates") or []
        if not isinstance(writes, list):
            writes = []
        if not isinstance(manifest_updates, list):
            manifest_updates = []
        return {"writes": writes, "manifest_updates": manifest_updates}

    # ---- application -----------------------------------------------------

    def apply_writes(
        self,
        proposal: dict,
        confirm_callback: Callable[[dict], bool] | None = None,
    ) -> list[str]:
        """Apply writes from a proposal. Returns human-readable applied lines."""
        applied: list[str] = []
        writes = proposal.get("writes") or []
        # Hold the store lock across the whole batch so consolidation and
        # per-turn pipelines do not interleave reads/writes on the same files.
        with self.store._lock:
            today_iso = datetime.now().strftime("%Y-%m-%d")
            people_meta_cache: dict[str, dict[str, Any]] = {}

            # Pre-pass: for any write touching people/<slug>.md, bump the
            # mention counter (creating a stub if needed) BEFORE the LLM-
            # proposed body lands. Cache the resulting frontmatter so later
            # tier-based filtering can consult it without an extra read.
            for write in writes:
                if not isinstance(write, dict):
                    continue
                # update_field is a frontmatter touch-up, not a mention; skip.
                if write.get("operation") == "update_field":
                    continue
                rel = write.get("file")
                slug = people_slug_from_path(rel) if isinstance(rel, str) else None
                if slug is None or slug in people_meta_cache:
                    continue
                relation = write.get("relation") if isinstance(write.get("relation"), str) else None
                try:
                    meta = record_mention(self.store, slug, today_iso, relation=relation)
                except Exception as exc:  # pragma: no cover - paranoia
                    logger.warning("record_mention failed for %s: %s", slug, exc)
                    continue
                people_meta_cache[slug] = meta
                try:
                    update_people_manifest_line(self.store, slug, meta)
                except Exception as exc:  # pragma: no cover
                    logger.warning("people manifest update failed for %s: %s", slug, exc)

            for write in writes:
                if not isinstance(write, dict):
                    continue
                layer = write.get("layer", 2)
                if layer == 2:
                    if confirm_callback is None:
                        continue
                    try:
                        ok = confirm_callback(write)
                    except Exception as exc:  # pragma: no cover
                        logger.warning("confirm_callback raised: %s", exc)
                        continue
                    if not ok:
                        continue

                # Tier guard: tier-3 (stub) people pages get Timeline-only writes.
                rel = write.get("file")
                slug = people_slug_from_path(rel) if isinstance(rel, str) else None
                if slug is not None and slug in people_meta_cache:
                    if not self._should_write_compiled(people_meta_cache[slug]):
                        write = _strip_compiled_truth(write)
                        if write is None:
                            logger.info(
                                "curator skipped compiled-truth write to tier-3 page: %s", rel
                            )
                            continue

                msg = self._apply_single(write)
                if msg:
                    applied.append(msg)
                    logger.info("curator wrote: %s (layer %s)", msg, layer)
        return applied

    def _should_write_compiled(self, frontmatter: dict) -> bool:
        """True when a page's tier permits compiled-truth content (tier <= 2)."""
        try:
            tier = int(frontmatter.get("tier", 3))
        except (TypeError, ValueError):
            tier = 3
        return tier <= 2

    def _apply_single(self, write: dict) -> str | None:
        op = write.get("operation")
        rel = write.get("file")
        if not isinstance(rel, str) or not rel:
            return None

        # Code-level enforcement: forbidden paths cannot be written by either
        # per-turn or consolidation pipelines, regardless of layer.
        if _is_forbidden(rel):
            logger.info("curator skipped forbidden path: %s", rel)
            return None

        # Reject obvious traversal / absolute-path attempts before the store
        # would itself reject them (lets us log a clearer reason).
        try:
            self.store._safe_rel(rel)
        except ValueError as exc:
            logger.warning("curator rejected unsafe path %r: %s", rel, exc)
            return None

        content = write.get("content", "")
        scope = _scope_of(rel)
        today = _today_iso()
        is_correction = _detect_correction(self._last_user_msg)
        source_type = write.get("source_type")
        if is_correction:
            source_type = "self-described"
        if source_type not in ("observed", "self-described", "inferred"):
            source_type = "observed"
        confidence = write.get("confidence") if source_type == "inferred" else None
        if source_type == "inferred" and confidence not in ("low", "medium", "high"):
            confidence = "low"
        timeline_summary = (write.get("reason") or content or "").strip().splitlines()[0:1]
        timeline_summary = timeline_summary[0] if timeline_summary else "(update)"
        if is_correction:
            timeline_summary = f"[CORRECTION] {timeline_summary}"
        timeline_source = "user" if is_correction or source_type == "self-described" else "session"
        compiled_update = bool(write.get("compiled_update", False))

        if op == "append":
            meta, body = self.store.read_file(rel)
            tagged = _wrap_state_bullets(content, source_type, confidence, today)
            template = _TEMPLATE_BY_SCOPE.get(scope)
            if template is not None:
                # Two-layer page: timeline-append by default; compiled rewrite only on flag.
                compiled, _ = split_layers(body or "")
                if compiled_update and tagged.strip():
                    new_compiled = compiled.rstrip() + "\n\n" + tagged.strip() + "\n"
                    body = rewrite_compiled(body or "", new_compiled)
                    if isinstance(meta, dict):
                        meta = dict(meta)
                        meta["last_updated"] = today
                # Always append a timeline entry citing this turn.
                body = append_timeline(body, today, timeline_source, timeline_summary)
                self.store.write_file(rel, meta, body)
                return f"Appended to {rel}"
            new_body = (
                (body.rstrip() + "\n\n" + tagged.strip() + "\n")
                if body
                else (tagged.strip() + "\n")
            )
            self.store.write_file(rel, meta, new_body)
            return f"Appended to {rel}"

        if op == "create":
            try:
                exists = self.store._safe_rel(rel).exists()
            except ValueError:
                return None
            if exists:
                logger.info("curator skipped create on existing file: %s", rel)
                return None
            meta, body = parse_frontmatter(content) if isinstance(content, str) else ({}, "")
            if not meta and isinstance(write.get("meta"), dict):
                meta = write["meta"]
                body = content if isinstance(content, str) else ""

            template = _TEMPLATE_BY_SCOPE.get(scope)
            if template is not None:
                # Render template, drop LLM-proposed body into Compiled-Truth State,
                # and seed Timeline with a creation entry.
                title = ""
                if isinstance(meta, dict):
                    title = str(meta.get("name") or meta.get("title") or "")
                if not title:
                    title = rel.rsplit("/", 1)[-1].removesuffix(".md").replace("-", " ").title()
                tagged_body = _wrap_state_bullets(body or "", source_type, confidence, today)
                fields: dict[str, object] = {
                    "title": title,
                    "name": title,
                    "last_updated": today,
                    "state": tagged_body.strip() or "- (none yet)",
                    "body": tagged_body.strip() or "(none yet)",
                }
                if isinstance(meta, dict):
                    for key in (
                        "aliases",
                        "relation",
                        "tier",
                        "domain",
                        "topic",
                        "status",
                        "started",
                        "target_date",
                        "summary",
                    ):
                        if meta.get(key) is not None:
                            fields[key] = meta.get(key)
                rendered = render_template(template, **fields)
                tmpl_meta, tmpl_body = parse_frontmatter(rendered)
                final_meta = dict(tmpl_meta)
                if isinstance(meta, dict):
                    for k, v in meta.items():
                        if k not in final_meta or final_meta[k] in ("", None):
                            final_meta[k] = v
                final_body = append_timeline(
                    tmpl_body, today, timeline_source, timeline_summary
                )
                self.store.write_file(rel, final_meta, final_body)
                return f"Created {rel}"

            self.store.write_file(rel, meta or {}, body)
            return f"Created {rel}"

        if op == "update_field":
            field = write.get("field")
            value = write.get("value")
            if not isinstance(field, str):
                return None
            if field == "immutable_core":
                logger.info("curator refused update_field on immutable_core: %s", rel)
                return None
            try:
                file_exists = self.store._safe_rel(rel).exists()
            except ValueError:
                return None
            if not file_exists:
                logger.info("curator refused update_field on missing file: %s", rel)
                return None
            meta, body = self.store.read_file(rel)
            meta = dict(meta)
            meta[field] = value
            self.store.write_file(rel, meta, body)
            return f"Updated {field} on {rel}"

        logger.warning("unknown curator operation: %r", op)
        return None

    # ---- manifest --------------------------------------------------------

    def apply_manifest_updates(self, updates: list[dict]) -> None:
        """Replace or append manifest lines per update entries."""
        with self.store._lock:
            for update in updates or []:
                if not isinstance(update, dict):
                    continue
                scope = update.get("scope")
                line_key = update.get("line_key")
                new_line = update.get("new_line")
                if not (
                    isinstance(scope, str)
                    and isinstance(line_key, str)
                    and isinstance(new_line, str)
                ):
                    continue
                # Strip newlines/CRs to prevent manifest-line injection; cap length.
                sanitized = new_line.replace("\r", " ").replace("\n", " ").strip()
                if not sanitized:
                    continue
                if len(sanitized) > _MANIFEST_LINE_MAX:
                    sanitized = sanitized[:_MANIFEST_LINE_MAX]
                # Likewise strip newlines from line_key — its substring search
                # must not span lines.
                line_key_clean = line_key.replace("\r", " ").replace("\n", " ")

                current = self.store.read_manifest(scope)
                lines = current.splitlines() if current else []
                replaced = False
                for i, line in enumerate(lines):
                    if line_key_clean in line:
                        lines[i] = sanitized
                        replaced = True
                        break
                if not replaced:
                    lines.append(sanitized)
                new_content = "\n".join(lines)
                if not new_content.endswith("\n"):
                    new_content += "\n"
                try:
                    self.store.write_manifest(scope, new_content)
                except ValueError as exc:
                    logger.warning("manifest write rejected for %r: %s", scope, exc)
                    continue
                logger.info("manifest updated: %s line %r", scope, line_key_clean)

    # ---- consolidation ---------------------------------------------------

    def consolidate_session(self, messages: list[dict]) -> list[str]:
        """Auto-dream: cross-turn fact extraction at session end.

        Reads full transcript + current scope manifests, asks the pro model for
        durable writes, applies them silently (no confirm gate). Returns a list
        of human-readable change descriptions for logging.
        """
        if not messages or len(messages) < self._CONSOLIDATION_MIN_TURNS:
            return []

        manifest_blocks: list[str] = []
        for scope in ("people", "preferences", "life", "threads", "events"):
            content = self.store.read_manifest(scope) or "(empty)"
            manifest_blocks.append(f"=== {scope}/_manifest.md ===\n{content}")
        manifests = "\n\n".join(manifest_blocks)
        transcript = _format_turns(messages)

        prompt = CONSOLIDATION_PROMPT.format(
            manifests=_safe_brace(manifests),
            transcript=_safe_brace(transcript),
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
        except Exception as exc:  # pragma: no cover
            logger.warning("consolidation LLM call failed: %s", exc)
            return []

        try:
            proposal = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("consolidation returned non-JSON: %r", raw[:200])
            return []

        writes = proposal.get("writes", []) or []
        manifest_updates = proposal.get("manifest_updates", []) or []

        # Force layer 1 (silent) for consolidation. The forbidden-path /
        # immutable-field guards live in `_apply_single` and apply uniformly.
        safe_writes: list[dict] = []
        for w in writes:
            if not isinstance(w, dict):
                continue
            w["layer"] = 1
            safe_writes.append(w)

        applied = self.apply_writes({"writes": safe_writes}, confirm_callback=None)
        self.apply_manifest_updates(manifest_updates)
        if applied:
            logger.info("consolidation applied %d writes", len(applied))
        return applied

    # ---- session digest --------------------------------------------------

    def summarize_session(self, messages: list[dict]) -> None:
        """Build a session digest and append to today's log."""
        if not messages:
            return
        transcript = _format_turns(messages)
        digest_prompt = (
            "You are summarizing an assistant session for a personal log.\n\n"
            "Output a concise markdown digest with three short sections:\n"
            "## What happened\n## Decisions / facts learned\n## Open threads\n\n"
            "Be terse. No filler. Use bullets. If a section has nothing, write '- (none)'.\n\n"
            f"# Transcript\n{transcript}\n"
        )
        digest = ""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": digest_prompt}],
            )
            digest = (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # pragma: no cover
            logger.warning("session digest LLM call failed: %s", exc)
            return
        if not digest:
            logger.warning("session digest empty; skipping log write")
            return

        today = datetime.now()
        month = today.strftime("%Y-%m")
        date = today.strftime("%Y-%m-%d")
        time_label = today.strftime("%H:%M")
        rel = f"log/{month}/{date}.md"

        with self.store._lock:
            meta, body = self.store.read_file(rel)
            section = f"\n## Session {time_label}\n\n{digest}\n"
            new_body = (body.rstrip() + "\n" + section) if body else section.lstrip("\n")
            self.store.write_file(rel, meta, new_body)

            # One-line monthly summary into log/_manifest.md.
            self._append_log_monthly(month, date, digest)

    def _append_log_monthly(self, month: str, date: str, digest: str) -> None:
        """Append a one-line digest summary under the YYYY-MM section of log/_manifest.md."""
        try:
            current = self.store.read_manifest("log")
        except ValueError as exc:
            logger.warning("log manifest read failed: %s", exc)
            return

        # Pull a single line from the digest as the summary.
        first = ""
        for line in digest.splitlines():
            stripped = line.strip().lstrip("-* ").strip()
            if stripped and not stripped.startswith("#"):
                first = stripped
                break
        if not first:
            first = "(session)"
        first = first.replace("\r", " ").replace("\n", " ")
        if len(first) > 200:
            first = first[:200]
        new_entry = f"- {date}: {first}"

        heading = f"## {month}"
        if not current:
            new_content = f"# Log Manifest\n\n{heading}\n{new_entry}\n"
        elif heading in current:
            new_content = _append_to_section(current, heading, new_entry)
        else:
            sep = "" if current.endswith("\n") else "\n"
            new_content = f"{current}{sep}\n{heading}\n{new_entry}\n"
        if not new_content.endswith("\n"):
            new_content += "\n"
        try:
            self.store.write_manifest("log", new_content)
        except ValueError as exc:
            logger.warning("log manifest write failed: %s", exc)


# ---- helpers -------------------------------------------------------------


def _strip_compiled_truth(write: dict) -> dict | None:
    """For a tier-3 people-page write, drop compiled-truth content; keep only timeline.

    Returns ``None`` when the write would be empty after stripping (e.g. an
    ``update_field`` on a non-tier field, or a body with no timeline section).
    The caller can then skip the write entirely.
    """
    op = write.get("operation")
    # update_field is allowed only when it touches frontmatter (tier/relation/etc).
    # Body-level field writes don't exist in this curator, so allow through.
    if op == "update_field":
        return write

    content = write.get("content")
    if not isinstance(content, str) or not content.strip():
        return None

    if op == "create":
        # Preserve frontmatter fence if any; strip compiled portion of body.
        meta, body = parse_frontmatter(content)
        compiled, timeline = split_layers(body)
        if not timeline.strip():
            return None
        new_body = join_layers("", timeline)
        new_content = dump_frontmatter(meta, new_body) if meta else new_body
        new_write = dict(write)
        new_write["content"] = new_content
        return new_write

    if op == "append":
        # Heuristic: if appended text looks like a timeline bullet, keep it;
        # otherwise drop. Timeline bullets start with '- ' and are ≤ a few lines.
        stripped = content.strip()
        if stripped.startswith("## Timeline"):
            return write
        # If multi-paragraph, treat as compiled-truth content and drop.
        if "\n\n" in stripped:
            return None
        # Otherwise allow short bullets / single lines through.
        return write

    return write


def _format_turns(turns: list[dict]) -> str:
    if not turns:
        return "(none)"
    out: list[str] = []
    for t in turns:
        role = t.get("role", "?")
        content = t.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        out.append(f"[{role}] {content}")
    return "\n".join(out)


def _extract_learnings(digest: str) -> str:
    """Pull the '## Decisions / facts learned' section from a digest.

    Returns the bullets verbatim (without the heading line) until the next
    ``##`` heading or EOF. Empty string if the heading is missing.
    """
    target = "## Decisions / facts learned"
    lines = digest.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == target:
            start = i + 1
            break
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start:]:
        if line.strip().startswith("## "):
            break
        out.append(line)
    return "\n".join(out).strip()


def _append_to_section(body: str, heading: str, content: str) -> str:
    """Insert ``content`` under ``heading`` in ``body``.

    If the heading exists, content is spliced just before the next ``## ``
    heading (or EOF). If absent, ``heading`` and ``content`` are appended.
    """
    if heading not in body:
        sep = "\n\n" if body and not body.endswith("\n") else ("\n" if body else "")
        return f"{body}{sep}{heading}\n\n{content.rstrip()}\n"

    idx = body.index(heading)
    after = idx + len(heading)
    # Find the next H2 after this heading.
    next_h2 = re.search(r"\n##\s", body[after:])
    insert_at = after + next_h2.start() if next_h2 else len(body)
    head_chunk = body[:insert_at].rstrip()
    tail_chunk = body[insert_at:]
    sep = "\n" if tail_chunk.startswith("\n") else "\n\n"
    return head_chunk + "\n\n" + content.rstrip() + sep + tail_chunk


# Back-compat alias for any external callers.
_append_under_heading = _append_to_section


# ---- manifest rebuild (function, not method) ----------------------------


def rebuild_manifest(
    store: AssistantMemoryStore,
    scope: str,
    settings: Settings,
) -> str:
    """Regenerate a scope manifest from scratch using the pro LLM. Pure — no writes."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope: {scope}")
    files = store.list_files(scope)
    file_blocks: list[str] = []
    for rel in files:
        meta, body = store.read_file(rel)
        block = (
            f"### {rel}\n"
            f"frontmatter: {json.dumps(meta, ensure_ascii=False, default=str)}\n"
            f"body:\n{body.strip()}\n"
        )
        file_blocks.append(block)
    files_str = "\n\n".join(file_blocks) if file_blocks else "(no files)"

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = (
        f"You are rebuilding `{scope}/_manifest.md` from scratch for a personal-assistant\n"
        "memory system. Follow this format exactly:\n\n"
        "- One line per file, pipe-delimited.\n"
        "- First column: `**<filename>.md**`.\n"
        "- Subsequent columns: key attributes / hooks for retrieval.\n"
        "- Time anchors must be inline + absolute (e.g. 'Apr 2026'), never 'recently'.\n"
        "- Manifests are HOOKS, not full facts.\n"
        "- For preferences: describe the kind of info inside, not the info itself.\n\n"
        f"Top of file should read:\n# {scope.title()} Manifest\nLast rebuilt: {today}\n\n"
        f"# Source files\n{files_str}\n\n"
        "Output the full manifest content only. No commentary, no fences."
    )

    client = create_client(settings)
    model = pick_model(settings, prefer="pro")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    content = (resp.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n", "", content)
        content = re.sub(r"\n```$", "", content)
    if not content.endswith("\n"):
        content += "\n"
    return content

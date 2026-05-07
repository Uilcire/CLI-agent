"""Tier-based people pages with mention counter (Phase D).

Every page under ``people/`` carries a small frontmatter contract:

    aliases: []
    relation: ""
    tier: 3
    mention_count: 0
    first_seen: YYYY-MM-DD
    last_mentioned: YYYY-MM-DD
    last_updated: YYYY-MM-DD

Tier escalation is purely deterministic — no LLM. Use ``record_mention`` to
bump a page's mention counter (creating a stub on first contact); the curator
calls it BEFORE applying LLM-proposed writes so the page exists at the right
tier when proposed body content lands.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .store import AssistantMemoryStore


logger = logging.getLogger(__name__)


TIER_1_RELATIONS: frozenset[str] = frozenset(
    {"mom", "dad", "spouse", "partner", "sibling", "best-friend"}
)

_PEOPLE_MANIFEST_LINE_MAX = 500


def compute_tier(mention_count: int, relation: str) -> int:
    """Return tier 1/2/3 from mention count and relation.

    Rules (in order):
      - mention_count >= 8 OR relation in TIER_1_RELATIONS -> 1
      - mention_count >= 3 OR relation set non-empty       -> 2
      - else                                                -> 3
    """
    rel = (relation or "").strip().lower()
    count = int(mention_count or 0)
    if count >= 8 or rel in TIER_1_RELATIONS:
        return 1
    if count >= 3 or rel:
        return 2
    return 3


def _stub_body(slug: str, today_iso: str) -> str:
    return (
        f"# {slug}\n\n"
        f"[stub — first mention {today_iso}]\n\n"
        "---\n\n"
        "## Timeline\n"
    )


def _default_meta(today_iso: str) -> dict[str, Any]:
    return {
        "aliases": [],
        "relation": "",
        "tier": 3,
        "mention_count": 0,
        "first_seen": today_iso,
        "last_mentioned": today_iso,
        "last_updated": today_iso,
    }


def record_mention(
    store: AssistantMemoryStore,
    slug: str,
    today_iso: str,
    relation: str | None = None,
) -> dict[str, Any]:
    """Bump the mention counter on ``people/<slug>.md``.

    Creates a stub page if one does not yet exist. Optionally sets/overrides
    ``relation``. Recomputes ``tier``. Returns the updated frontmatter dict.
    """
    if not isinstance(slug, str) or not slug:
        raise ValueError("slug must be a non-empty string")
    # Reject path-segment characters so a poisoned slug can't mint orphaned
    # nested pages that the manifest regex won't find later.
    if "/" in slug or "\\" in slug or ".." in slug or "\x00" in slug:
        raise ValueError(f"slug must not contain path separators or '..': {slug!r}")
    rel_path = f"people/{slug}.md"

    with store._lock:
        meta, body = store.read_file(rel_path)
        is_new = not meta and not body
        if is_new:
            meta = _default_meta(today_iso)
            body = _stub_body(slug, today_iso)
        else:
            meta = dict(meta)
            meta.setdefault("aliases", [])
            meta.setdefault("relation", "")
            meta.setdefault("tier", 3)
            meta.setdefault("mention_count", 0)
            meta.setdefault("first_seen", today_iso)
            meta.setdefault("last_mentioned", today_iso)
            meta.setdefault("last_updated", today_iso)

        try:
            current_count = int(meta.get("mention_count", 0))
        except (TypeError, ValueError):
            current_count = 0
        # Floor at 0 so a poisoned negative count can't suppress tier promotion.
        current_count = max(0, current_count)
        meta["mention_count"] = current_count + 1
        meta["last_mentioned"] = today_iso
        meta["last_updated"] = today_iso

        if relation is not None:
            meta["relation"] = (relation or "").strip().lower()

        meta["tier"] = compute_tier(meta["mention_count"], str(meta.get("relation", "")))

        store.write_file(rel_path, meta, body)
        return meta


# ---- manifest helper ----------------------------------------------------


def _format_aliases(aliases: Any) -> str:
    if isinstance(aliases, list):
        items = [str(a).strip() for a in aliases if str(a).strip()]
    elif isinstance(aliases, str) and aliases.strip():
        items = [aliases.strip()]
    else:
        items = []
    return ", ".join(items)


def _flat(value: Any) -> str:
    """Coerce to str, drop CR/LF so the value can never break the one-line manifest row."""
    return str(value if value is not None else "").replace("\r", " ").replace("\n", " ").strip()


def format_people_manifest_line(slug: str, meta: dict[str, Any]) -> str:
    """Format one manifest row for ``people/<slug>.md`` from its frontmatter.

    Self-sanitizing: every interpolated field is flattened to a single line so
    poisoned frontmatter (newlines in ``relation`` / ``aliases`` / ``last_*``)
    cannot break the one-line manifest contract for any caller.
    """
    tier = _flat(meta.get("tier", 3))
    relation = _flat(meta.get("relation")) or "-"
    mentions = _flat(meta.get("mention_count", 0))
    last = _flat(meta.get("last_mentioned") or meta.get("last_updated") or "-") or "-"
    aliases = _flat(_format_aliases(meta.get("aliases")))
    safe_slug = _flat(slug)
    line = (
        f"- **{safe_slug}.md** | tier:{tier} | relation:{relation} | "
        f"mentions:{mentions} | last:{last}"
    )
    if aliases:
        line += f" | aliases: {aliases}"
    return line


def update_people_manifest_line(
    store: AssistantMemoryStore,
    slug: str,
    meta: dict[str, Any],
) -> None:
    """Replace (or append) the manifest line for ``people/<slug>.md``."""
    if not isinstance(slug, str) or not slug:
        return
    new_line = format_people_manifest_line(slug, meta)
    sanitized = new_line.replace("\r", " ").replace("\n", " ").strip()
    if not sanitized:
        return
    if len(sanitized) > _PEOPLE_MANIFEST_LINE_MAX:
        sanitized = sanitized[:_PEOPLE_MANIFEST_LINE_MAX]

    line_key = f"**{slug}.md**"
    with store._lock:
        current = store.read_manifest("people")
        lines = current.splitlines() if current else []
        replaced = False
        for i, line in enumerate(lines):
            if line_key in line:
                lines[i] = sanitized
                replaced = True
                break
        if not replaced:
            lines.append(sanitized)
        new_content = "\n".join(lines)
        if not new_content.endswith("\n"):
            new_content += "\n"
        try:
            store.write_manifest("people", new_content)
        except ValueError as exc:  # pragma: no cover - paranoia
            logger.warning("people manifest write rejected: %s", exc)


# ---- write filtering ----------------------------------------------------


_PEOPLE_PATH_RE = re.compile(r"^people/([^/]+)\.md$")


def people_slug_from_path(rel: str) -> str | None:
    """Return the slug for a ``people/<slug>.md`` path, else None."""
    if not isinstance(rel, str):
        return None
    match = _PEOPLE_PATH_RE.match(rel.strip())
    return match.group(1) if match else None


def should_write_compiled(frontmatter: dict[str, Any]) -> bool:
    """True when a page's tier permits Compiled-Truth-style content (tier <= 2)."""
    try:
        tier = int(frontmatter.get("tier", 3))
    except (TypeError, ValueError):
        tier = 3
    return tier <= 2

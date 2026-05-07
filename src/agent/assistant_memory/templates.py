"""Page templates for new memory entries.

Each template uses ``{field}`` placeholders. Render with :func:`render_template`,
which substitutes provided fields and falls back to safe empty defaults.

All templates carry the canonical two-layer shape — Compiled Truth above, an
empty Timeline section below. The Timeline section is created up-front so the
curator can always ``append_timeline`` without conditionally creating it.
"""

from __future__ import annotations

from string import Formatter


PERSON_TEMPLATE = """---
name: {name}
aliases: {aliases}
relation: {relation}
tier: {tier}
last_updated: {last_updated}
---
# {name}

> {summary}

## State
{state}

## What I Know About Them
{what_i_know}

## Communication Style
{communication_style}

## Open Threads
{open_threads}

## See Also
{see_also}

---

## Timeline
"""


LIFE_DOMAIN_TEMPLATE = """---
domain: {domain}
last_updated: {last_updated}
---
# {title}

> {summary}

## State
{state}

## Open Threads
{open_threads}

## See Also
{see_also}

---

## Timeline
"""


THREAD_TEMPLATE = """---
status: {status}
started: {started}
target_date: {target_date}
last_updated: {last_updated}
---
# {title}

> {summary}

## Goal
{goal}

## Current Progress
{current_progress}

## Open Threads
{open_threads}

## See Also
{see_also}

---

## Timeline
"""


PREFERENCE_TEMPLATE = """---
topic: {topic}
last_updated: {last_updated}
---
# {title}

> {summary}

{body}

## See Also
{see_also}

---

## Timeline
"""


_DEFAULTS: dict[str, str] = {
    "name": "",
    "title": "",
    "aliases": "",
    "relation": "",
    "tier": "3",
    "last_updated": "",
    "summary": "(no summary yet)",
    "state": "- (none yet)",
    "what_i_know": "- (none yet)",
    "communication_style": "- (none yet)",
    "open_threads": "- (none)",
    "see_also": "- (none)",
    "domain": "",
    "status": "active",
    "started": "",
    "target_date": "",
    "goal": "- (none yet)",
    "current_progress": "- (none yet)",
    "topic": "",
    "body": "(none yet)",
}


class _SafeDict(dict):
    """``str.format_map`` helper — returns ``""`` for missing keys."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return _DEFAULTS.get(key, "")


def render_template(template: str, **fields: object) -> str:
    """Substitute ``{field}`` placeholders, defaulting missing values to safe blanks.

    Unknown placeholders resolve to either a per-field default (see ``_DEFAULTS``)
    or the empty string. Provided ``None`` values are coerced to ``""``.
    """
    safe: _SafeDict = _SafeDict()
    # Pre-populate with declared fields used in the template, so callers see
    # consistent defaults even when they don't pass a value.
    for _, name, _, _ in Formatter().parse(template):
        if name and name not in safe:
            safe[name] = _DEFAULTS.get(name, "")
    for key, value in fields.items():
        safe[key] = "" if value is None else str(value)
    return template.format_map(safe)

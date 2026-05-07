"""Two-layer page utilities.

A page body is split into:

- **Compiled Truth** (above the separator): current state, can be rewritten.
- **Timeline** (below): append-only event log, never rewritten.

Separator format::

    <compiled truth>

    ---

    ## Timeline
    - **YYYY-MM-DD** | source — what happened

A high-value fact bullet may carry a sourcing tag — see ``format_sourced_bullet``.
"""

from __future__ import annotations


TIMELINE_SEPARATOR = "\n\n---\n\n## Timeline\n"
_TIMELINE_HEADER = "## Timeline"

_VALID_SOURCE_TYPES = ("observed", "self-described", "inferred")
_VALID_CONFIDENCE = ("low", "medium", "high")


def split_layers(body: str) -> tuple[str, str]:
    """Return ``(compiled_truth, timeline)``.

    ``timeline`` includes the ``## Timeline`` header line. If no separator is
    present, the entire body is returned as compiled truth and timeline is
    empty.
    """
    if not body:
        return "", ""
    text = body
    # Find the timeline header on its own line, preceded by a thematic break.
    sep_idx = text.find(TIMELINE_SEPARATOR)
    if sep_idx != -1:
        compiled = text[:sep_idx]
        # Skip the leading "\n\n---\n\n" — keep "## Timeline\n..." in the timeline.
        timeline_start = sep_idx + len("\n\n---\n\n")
        timeline = text[timeline_start:]
        return compiled.rstrip("\n"), timeline.rstrip("\n")
    # Fallback: bare "## Timeline" header without explicit thematic break.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == _TIMELINE_HEADER:
            compiled = "\n".join(lines[:i]).rstrip("\n")
            # Strip trailing thematic-break line if present.
            if compiled.endswith("---"):
                compiled = compiled[:-3].rstrip("\n")
            timeline = "\n".join(lines[i:]).rstrip("\n")
            return compiled, timeline
    return text.rstrip("\n"), ""


def join_layers(compiled: str, timeline: str) -> str:
    """Re-join compiled truth and timeline with exactly one separator.

    If ``timeline`` is empty, returns just the compiled truth (with a single
    trailing newline).
    """
    compiled_clean = (compiled or "").rstrip("\n")
    timeline_clean = (timeline or "").strip("\n")
    if not timeline_clean:
        return compiled_clean + "\n" if compiled_clean else ""
    # Strip leading "## Timeline" header — TIMELINE_SEPARATOR already supplies it.
    header_prefix = _TIMELINE_HEADER + "\n"
    if timeline_clean.startswith(header_prefix):
        timeline_body = timeline_clean[len(header_prefix):]
    elif timeline_clean == _TIMELINE_HEADER:
        timeline_body = ""
    else:
        timeline_body = timeline_clean
    if timeline_body:
        return f"{compiled_clean}{TIMELINE_SEPARATOR}{timeline_body}\n"
    return f"{compiled_clean}{TIMELINE_SEPARATOR}\n".rstrip() + "\n"


def append_timeline(body: str, date_iso: str, source: str, summary: str) -> str:
    """Append a new ``- **DATE** | source — summary`` bullet to the timeline.

    If the page has no timeline section, one is created.
    """
    compiled, timeline = split_layers(body or "")
    summary_clean = (summary or "").strip().replace("\n", " ")
    source_clean = (source or "").strip().replace("\n", " ") or "session"
    bullet = f"- **{date_iso}** | {source_clean} — {summary_clean}"
    if not timeline:
        new_timeline = f"{_TIMELINE_HEADER}\n{bullet}"
    else:
        new_timeline = timeline.rstrip("\n") + "\n" + bullet
    return join_layers(compiled, new_timeline)


def rewrite_compiled(body: str, new_compiled: str) -> str:
    """Replace the compiled-truth portion, preserving the timeline verbatim."""
    _, timeline = split_layers(body or "")
    return join_layers(new_compiled or "", timeline)


def format_sourced_bullet(
    text: str,
    source_type: str,
    date: str | None = None,
    confidence: str | None = None,
) -> str:
    """Return a markdown bullet annotated with provenance.

    ``source_type`` must be one of ``observed``, ``self-described``, ``inferred``.
    For ``inferred``, ``confidence`` is required and must be ``low|medium|high``.
    """
    if source_type not in _VALID_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of {_VALID_SOURCE_TYPES}, got {source_type!r}"
        )
    if source_type == "inferred":
        if confidence is None:
            raise ValueError("confidence is required when source_type is 'inferred'")
        if confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"confidence must be one of {_VALID_CONFIDENCE}, got {confidence!r}"
            )

    tag_parts = [source_type]
    if confidence is not None and source_type == "inferred":
        tag_parts.append(f"confidence: {confidence}")
    if date:
        # Strip ']' to keep the canonical _[...]_ tag round-trip safe.
        tag_parts.append(str(date).replace("]", "").replace("\n", " ").strip())
    tag = ", ".join(tag_parts)
    # Flatten newlines in the body so a malicious bullet text can't splice
    # pseudo-bullets into a State section.
    flat_text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    return f"- {flat_text} _[{tag}]_"

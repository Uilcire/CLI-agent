"""Edit personality.json in agent-memory."""

import json
from pathlib import Path


def personality_edit(updates: dict, path: str = "agent-memory/personality.json") -> str:
    """
    Merge key-value updates into personality.json and save.

    Args:
        updates: Key-value pairs to merge (e.g. {"soul": "new text"}).
                 Only provided keys are updated; others are left unchanged.
                 immutable_core cannot be edited.
        path: Path to personality.json (default: agent-memory/personality.json).

    Returns:
        Success message or error string.
    """
    try:
        p = Path(path)
        if not updates:
            return "Error: updates cannot be empty."

        if "immutable_core" in updates:
            return "Error: immutable_core cannot be edited."

        # Ensure all values are strings
        for k, v in updates.items():
            if not isinstance(v, str):
                return f"Error: value for '{k}' must be a string."

        # Load existing or start fresh
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {}

        # Reject soul over 300 words; ask agent to summarize
        if "soul" in updates:
            words = [w for w in updates["soul"].split() if w]
            if len(words) > 300:
                n = len(words)
                return (
                    f"Error: soul is {n} words (max 300). "
                    "Please summarize it to under 300 words and call personality_edit again."
                )

        # Merge updates
        data.update(updates)

        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"Updated personality.json: {list(updates.keys())}"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in {path}: {e}"
    except OSError as e:
        return f"Error: {e}"

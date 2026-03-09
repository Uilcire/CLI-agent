"""Replace a unique string in a file. Primary editing tool."""

from pathlib import Path

from agent.tools.edit_common import atomic_write, syntax_check, validate_path


def str_replace(path: str, old_str: str, new_str: str) -> str:
    """
    Replace a unique occurrence of old_str with new_str in the file.
    Uses atomic write (temp file + rename).
    """
    v = validate_path(path)
    if isinstance(v, str):
        return v
    resolved = v

    if not resolved.exists():
        return f"Error: File not found: {path}"
    if resolved.is_dir():
        return f"Error: {path} is a directory, not a file"

    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error: Could not read file: {e}"

    count = content.count(old_str)
    if count == 0:
        return f"Error: string not found (old_str must match exactly, including whitespace and newlines)"
    if count > 1:
        return f"Error: ambiguous match (old_str appears {count} times; must appear exactly once)"

    new_content = content.replace(old_str, new_str, 1)
    try:
        atomic_write(resolved, new_content)
    except Exception as e:
        return f"Error: {e}"

    warning = syntax_check(resolved, new_content)
    if warning:
        return f"Replaced 1 occurrence in {path}. {warning}"
    return f"Replaced 1 occurrence in {path}"

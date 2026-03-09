"""Overwrite entire file. Fallback for large edits."""

from pathlib import Path

from agent.tools.edit_common import atomic_write, syntax_check, validate_path


def file_rewrite(path: str, content: str) -> str:
    """
    Overwrite the entire file with new content.
    Uses atomic write (temp file + rename).
    """
    v = validate_path(path)
    if isinstance(v, str):
        return v
    resolved = v

    if resolved.exists() and resolved.is_dir():
        return f"Error: {path} is a directory, not a file"

    try:
        atomic_write(resolved, content)
    except Exception as e:
        return f"Error: {e}"

    warning = syntax_check(resolved, content)
    if warning:
        return f"Wrote {path}. {warning}"
    return f"Wrote {path}"

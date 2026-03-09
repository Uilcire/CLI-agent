"""Shared logic for file-editing tools: path validation, atomic write, syntax check."""

import ast
import json
import tempfile
from pathlib import Path


def get_allowed_root() -> Path:
    """Return the workspace root (cwd). Only files under this may be edited."""
    return Path.cwd().resolve()


def validate_path(path: str) -> Path | str:
    """
    Validate that the path is within the allowed directory.
    Reject paths with .. that escape the allowlist.
    Returns the resolved Path on success, or an error string on failure.
    """
    root = get_allowed_root()
    try:
        resolved = Path(path).resolve()
    except OSError as e:
        return f"Error: Invalid path: {e}"
    if ".." in Path(path).parts:
        return f"Error: Path must not contain '..' segments"
    try:
        resolved.relative_to(root)
    except ValueError:
        return f"Error: Path is outside allowed directory: {resolved}"
    return resolved


def atomic_write(path: Path, content: str) -> None:
    """
    Write content to a temp file, then atomically rename to the target path.
    Creates parent directories if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=".tmp_", suffix=path.suffix or ""
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def syntax_check(path: Path, content: str) -> str | None:
    """
    Run syntax validation for known file types.
    Returns a warning string if validation fails, None if OK or unknown type.
    Does not raise — returns a descriptive warning for the agent to self-correct.
    """
    suf = path.suffix.lower()
    if suf == ".py":
        try:
            ast.parse(content)
            return None
        except SyntaxError as e:
            return f"Warning: Python syntax error at line {e.lineno}: {e.msg}"
    if suf == ".json":
        try:
            json.loads(content)
            return None
        except json.JSONDecodeError as e:
            return f"Warning: JSON syntax error at line {e.lineno}: {e.msg}"
    # .yaml, .js, .ts: no built-in validator; skip
    return None

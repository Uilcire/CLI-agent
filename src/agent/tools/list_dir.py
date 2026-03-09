"""List directory contents. Read-only tool."""

from pathlib import Path


def list_dir(path: str = ".") -> str:
    """
    List files and directories at the given path.

    Args:
        path: Path to list (default: current directory).

    Returns:
        Human-readable list of entries, one per line, with (dir) suffix for directories.
        On error, returns an error message.
    """
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: Path does not exist: {path}"
        if not p.is_dir():
            return f"Error: {path} is not a directory"
        lines = []
        for entry in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            name = entry.name
            if entry.is_dir():
                lines.append(f"{name}/")
            else:
                lines.append(name)
        return "\n".join(lines) if lines else "(empty)"
    except PermissionError:
        return f"Error: Permission denied reading {path}"
    except OSError as e:
        return f"Error: {e}"

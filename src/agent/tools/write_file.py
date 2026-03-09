"""Write file contents. Write tool."""

from pathlib import Path


def write_file(path: str, content: str) -> str:
    """
    Create or overwrite a file with the given content.

    Args:
        path: Path to the file.
        content: Full content to write.

    Returns:
        Success message or error string.
    """
    try:
        Path(path).write_text(content, encoding="utf-8")
        return f"Wrote {path}"
    except IsADirectoryError:
        return f"Error: {path} is a directory, not a file"
    except PermissionError:
        return f"Error: Permission denied writing {path}"
    except OSError as e:
        return f"Error: {e}"

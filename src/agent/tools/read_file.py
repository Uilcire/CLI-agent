"""Read file contents. Read-only tool."""

from pathlib import Path


def read_file(path: str) -> str:
    """
    Read the contents of a file.

    Args:
        path: Path to the file (relative to cwd or absolute).

    Returns:
        The file contents as a string. On error, returns an error message.
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except IsADirectoryError:
        return f"Error: {path} is a directory, not a file"
    except PermissionError:
        return f"Error: Permission denied reading {path}"
    except UnicodeDecodeError as e:
        return f"Error: File is not valid UTF-8: {path} ({e})"
    except OSError as e:
        return f"Error: {e}"

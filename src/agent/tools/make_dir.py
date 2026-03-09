"""Create directory. Write tool."""

from pathlib import Path


def make_dir(path: str, parents: bool = True) -> str:
    """
    Create a directory at the given path.

    Args:
        path: Path to the directory to create.
        parents: If True, create parent directories as needed. Default True.

    Returns:
        Success message or error string.
    """
    try:
        Path(path).mkdir(parents=parents, exist_ok=True)
        return f"Created directory {path}"
    except FileExistsError:
        return f"Error: {path} exists and is not a directory"
    except PermissionError:
        return f"Error: Permission denied creating {path}"
    except OSError as e:
        return f"Error: {e}"

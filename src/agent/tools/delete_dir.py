"""Delete a directory recursively. Asks for permission via confirm box unless previously granted."""

from agent.tools.delete_common import confirm_and_delete


def delete_dir(path: str) -> str:
    """
    Delete a directory and all its contents at the given path.
    Shows a confirmation dialog unless the path was previously granted.

    Args:
        path: Path to the directory to delete (relative or absolute).

    Returns:
        Success message or error string.
    """
    return confirm_and_delete(path, is_dir=True)

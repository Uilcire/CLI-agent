"""Delete a file. Asks for permission via confirm box unless previously granted."""

from agent.tools.delete_common import confirm_and_delete


def delete_file(path: str) -> str:
    """
    Delete a file at the given path.
    Shows a confirmation dialog unless the path was previously granted.

    Args:
        path: Path to the file to delete (relative or absolute).

    Returns:
        Success message or error string.
    """
    return confirm_and_delete(path, is_dir=False)

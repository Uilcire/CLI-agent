"""Shared logic for delete tools: confirm UI and delete execution."""

from pathlib import Path

from agent.logger import get_logger
from agent.permissions import grant_delete_permission, has_delete_permission

log = get_logger(__name__)


def confirm_and_delete(path: str, is_dir: bool) -> str:
    """
    Show confirm UI if needed, perform delete, return result message.
    Imports confirm_delete lazily to avoid circular imports.
    """
    from agent.cli.display import confirm_delete

    p = Path(path)
    try:
        resolved = p.resolve()
    except OSError as e:
        return f"Error: {e}"

    if not resolved.exists():
        return f"Error: Path does not exist: {path}"

    if is_dir and not resolved.is_dir():
        return f"Error: {path} is not a directory"
    if not is_dir and not resolved.is_file():
        return f"Error: {path} is not a file"

    if has_delete_permission(str(resolved)):
        log.debug("Delete skipped prompt (permission granted): %s", resolved)
        return _do_delete(resolved, is_dir)

    choice = confirm_delete(str(resolved))
    if choice == "cancel":
        return "Delete cancelled by user."
    if choice == "delete_grant":
        grant_delete_permission(str(resolved))
    # delete_no_grant: just delete, don't add to granted
    return _do_delete(resolved, is_dir)


def _do_delete(path: Path, is_dir: bool) -> str:
    """Actually perform the delete. path is resolved and exists."""
    import shutil

    try:
        if is_dir:
            shutil.rmtree(path)
            return f"Deleted directory {path}"
        path.unlink()
        return f"Deleted file {path}"
    except PermissionError:
        return f"Error: Permission denied deleting {path}"
    except OSError as e:
        return f"Error: {e}"

"""Permission gates for destructive operations (e.g. delete)."""

from pathlib import Path

from agent.logger import get_logger

log = get_logger(__name__)

# Paths granted for deletion this session (absolute, resolved)
_granted_delete_paths: set[str] = set()


def has_delete_permission(path: str) -> bool:
    """
    True if path or any of its parents has been granted for deletion.
    A path is covered if it equals a granted path or is a descendant of one.
    """
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        return False
    if resolved in _granted_delete_paths:
        return True
    sep = "/"
    for granted in _granted_delete_paths:
        if resolved == granted:
            return True
        if resolved.startswith(granted + sep) or resolved.startswith(granted + "\\"):
            return True
    return False


def grant_delete_permission(path: str) -> None:
    """Mark path as granted for future deletes (no confirmation needed for this session)."""
    try:
        resolved = str(Path(path).resolve())
        _granted_delete_paths.add(resolved)
        log.info("Delete permission granted for: %s", resolved)
    except OSError:
        pass


def revoke_delete_permission(path: str) -> None:
    """Remove path from granted set. Used when user explicitly revokes."""
    try:
        _granted_delete_paths.discard(str(Path(path).resolve()))
    except OSError:
        pass


def clear_delete_permissions() -> None:
    """Clear all granted delete paths. Mainly for testing."""
    _granted_delete_paths.clear()


def get_granted_delete_paths() -> tuple[str, ...]:
    """Return granted delete paths (sorted, for stable output)."""
    return tuple(sorted(_granted_delete_paths))

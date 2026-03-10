"""Permission gates and safety checks."""

from agent.permissions.gates import (
    clear_delete_permissions,
    get_granted_delete_paths,
    grant_delete_permission,
    has_delete_permission,
    revoke_delete_permission,
)

__all__ = [
    "clear_delete_permissions",
    "get_granted_delete_paths",
    "grant_delete_permission",
    "has_delete_permission",
    "revoke_delete_permission",
]

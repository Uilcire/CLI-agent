"""Tool registry: definitions for the API and execution dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.logger import get_logger
from agent.tools import (
    beautify as beautify_module,
    check_permissions as check_permissions_module,
    delete_dir as delete_dir_module,
    delete_file as delete_file_module,
    dummy,
    file_rewrite as file_rewrite_module,
    list_dir as list_dir_module,
    make_dir as make_dir_module,
    read_file as read_file_module,
    str_replace as str_replace_module,
    web_search as web_search_module,
    write_file as write_file_module,
)
from agent.tools.activate_skill import activate_skill as _activate_skill_fn

if TYPE_CHECKING:
    from agent.core.state import ConversationState
    from agent.skills.manager import SkillManager

log = get_logger(__name__)

# Module-level skill context — set once at startup via init().
_skill_manager: SkillManager | None = None
_state: ConversationState | None = None


def init(skill_manager: SkillManager, state: ConversationState) -> None:
    """Inject the SkillManager and ConversationState so execute() can reach them."""
    global _skill_manager, _state
    _skill_manager = skill_manager
    _state = state


def get_tools() -> list[dict]:  # noqa: PLR0912
    """
    Return tool definitions for the OpenAI API.

    Each tool is a dict with:
    - type: "function" (OpenAI only supports function tools)
    - function: { name, description, parameters }
    - parameters: JSON Schema (type, properties, required)
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo back the given message. Use to verify tool use works.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to echo back.",
                        }
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file. Use for inspecting code, config, or any text file. Path can be relative or absolute.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file (relative to cwd or absolute)",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List files and directories at the given path. Use to explore project structure. Default path is current directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to list (default: current directory)",
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Create or overwrite a file with the given content. Use for new files or full replacements.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "content": {"type": "string", "description": "Full content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "str_replace",
                "description": "Replace a unique string in a file. Primary editing tool. old_str must match exactly once (including whitespace/newlines). Use for targeted edits. One edit per call. Re-read the file before making further edits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file (relative or absolute within workspace)"},
                        "old_str": {"type": "string", "description": "Exact string to find and replace (must appear exactly once)"},
                        "new_str": {"type": "string", "description": "Replacement string (empty string to delete)"},
                    },
                    "required": ["path", "old_str", "new_str"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "make_dir",
                "description": "Create a directory at the given path. Creates parent directories if needed. Use when setting up project structure or scaffolding.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the directory to create (relative or absolute)"},
                        "parents": {"type": "boolean", "description": "Create parent directories as needed (default: true)", "default": True},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "file_rewrite",
                "description": "Overwrite the entire file with new content. Use only when str_replace would be impractical (many changes, restructure, reformat). Prefer str_replace for small, targeted edits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file (relative or absolute within workspace)"},
                        "content": {"type": "string", "description": "Complete new file content"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Delete a file at the given path. A confirmation dialog pops up automatically when permission not granted. Call when user confirms deletion (e.g. 'yes').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to delete (relative or absolute)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_dir",
                "description": "Delete a directory and all its contents recursively. A confirmation dialog pops up automatically when permission not granted. Call when user confirms deletion (e.g. 'yes').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the directory to delete (relative or absolute)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_permissions",
                "description": "Check current delete permissions. Without path: list all granted paths. With path: check if that path has delete permission (won't prompt when deleting).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Optional path to check. If omitted, lists all granted paths."},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information. Use when you need current, real-world information beyond the codebase. Requires PERPLEXITY_API_KEY in .env.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query string"},
                        "max_results": {"type": "integer", "description": "Maximum number of results (default: 7)", "default": 7},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "beautify",
                "description": "Reformat text to be clearer and more human-readable using an LLM. Use on raw output, tool results, or any dense information before presenting to the user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Raw text to beautify"},
                    },
                    "required": ["text"],
                },
            },
        },
    ]

    if _skill_manager and not _skill_manager.is_empty():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "activate_skill",
                    "description": (
                        "Load the full instructions for a named skill into context. "
                        "Call this when the current task matches a skill's description."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": _skill_manager.names(),
                                "description": "The skill name to activate.",
                            }
                        },
                        "required": ["name"],
                    },
                },
            }
        )

    return tools


def execute(name: str, args: dict) -> str:
    """
    Run a tool by name and return the result as a string.

    Args:
        name: Tool name (e.g. "echo").
        args: Dict of arguments from the model's tool_call (parsed from JSON).

    Returns:
        String result for tool message content. On failure, returns "Error: ..."
        so the model can adapt instead of crashing the loop.
    """
    try:
        log.debug("Dispatching tool %s with args %s", name, args)
        if name == "echo":
            return dummy.echo(args["message"])
        if name == "read_file":
            return read_file_module.read_file(args["path"])
        if name == "list_dir":
            return list_dir_module.list_dir(args.get("path", "."))
        if name == "write_file":
            return write_file_module.write_file(args["path"], args["content"])
        if name == "str_replace":
            return str_replace_module.str_replace(
                args["path"], args["old_str"], args["new_str"]
            )
        if name == "make_dir":
            return make_dir_module.make_dir(args["path"], args.get("parents", True))
        if name == "file_rewrite":
            return file_rewrite_module.file_rewrite(args["path"], args["content"])
        if name == "delete_file":
            return delete_file_module.delete_file(args["path"])
        if name == "delete_dir":
            return delete_dir_module.delete_dir(args["path"])
        if name == "check_permissions":
            return check_permissions_module.check_permissions(args.get("path"))
        if name == "web_search":
            return web_search_module.web_search(
                args["query"], args.get("max_results", 7)
            )
        if name == "beautify":
            return beautify_module.beautify(args["text"])
        if name == "activate_skill":
            if _skill_manager is None or _state is None:
                return "Error: skill system not initialized."
            return _activate_skill_fn(args["name"], _skill_manager, _state)
        log.warning("Unknown tool requested: %s", name)
        return f"Error: Unknown tool: {name}"
    except Exception as e:
        log.error("Tool %s failed: %s", name, e, exc_info=True)
        return f"Error: {e}"

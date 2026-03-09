"""Tool registry: definitions for the API and execution dispatch."""

from agent.tools import dummy


def get_tools() -> list[dict]:
    """
    Return tool definitions for the OpenAI API.

    Each tool is a dict with:
    - type: "function" (OpenAI only supports function tools)
    - function: { name, description, parameters }
    - parameters: JSON Schema (type, properties, required)
    """
    return [
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
        }
    ]


def execute(name: str, args: dict) -> str:
    """
    Run a tool by name and return the result as a string.

    Args:
        name: Tool name (e.g. "echo").
        args: Dict of arguments from the model's tool_call (parsed from JSON).

    Returns:
        String result for tool message content.

    Raises:
        ValueError: If the tool name is unknown.
    """
    if name == "echo":
        return dummy.echo(args["message"])
    raise ValueError(f"Unknown tool: {name}")

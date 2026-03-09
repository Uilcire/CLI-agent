"""A minimal dummy tool for testing the tool-use loop."""


def echo(message: str) -> str:
    """
    Echo back the given message. Used to verify tool execution works.

    Args:
        message: The string to echo back.

    Returns:
        The same string, unchanged.
    """
    return message

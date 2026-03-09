"""REPL entry point: run the agent in an interactive loop."""

import sys

from agent.config.settings import load_settings
from agent.cli.display import print_assistant, print_banner
from agent.core.loop import run


def main() -> None:
    """Run the CLI agent REPL."""
    try:
        settings = load_settings()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print_banner()
    print("Type a message or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except KeyboardInterrupt:
            print("\nBye.")
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            print("Bye.")
            break
        response = run(user_input, settings)
        print_assistant(response)

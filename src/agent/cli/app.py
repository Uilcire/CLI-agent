"""REPL entry point: run the agent in an interactive loop."""

import sys

from agent.logger import get_logger
from agent.config.settings import load_settings
from agent.cli.display import print_banner, prompt_user, stream_assistant
from agent.core.loop import run_streaming
from agent.core.state import ConversationState

log = get_logger(__name__)


def main() -> None:
    """Run the CLI agent REPL."""
    try:
        settings = load_settings()
        log.info("Settings loaded: model=%s, max_tokens=%s", settings.model, settings.max_tokens)
    except ValueError as e:
        log.error("Settings error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print_banner()
    print("Type a message or 'quit' to exit.")
    log.info("Agent started, waiting for user input")

    state = ConversationState(
        system_prompt=(
            "You are a helpful cli code assistant.\n\n"
            "For deletions: When the user confirms they want to delete (e.g. 'yes', 'delete it', 'go ahead'), "
            "call delete_file or delete_dir directly. Do not ask for explicit text formats like 'DELETE ./path'. "
            "A confirmation dialog will automatically pop up when permission has not been granted this session."
        )
    )
    while True:
        try:
            user_input = prompt_user()
        except KeyboardInterrupt:
            log.info("Agent stopped by user (Ctrl+C)")
            print("\nBye.")
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            log.info("Agent stopped by user (quit/exit)")
            print("Bye.")
            break
        log.info("User message received: %s", user_input[:100] + ("..." if len(user_input) > 100 else ""))
        events = run_streaming(user_input, settings, state=state)
        final_text = stream_assistant(events)
        log.info("Turn complete, assistant reply length=%d chars", len(final_text) if final_text else 0)

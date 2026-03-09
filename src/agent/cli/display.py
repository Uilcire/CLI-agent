"""Display layer: pretty-print assistant output using Rich."""

from rich.console import Console
from rich.panel import Panel
from rich.box import ROUNDED


# Neon blue hex
NEON_BLUE = "#00d4ff"


def print_banner() -> None:
    """Print the CLI agent banner on startup (neon blue, rounded border)."""
    console = Console()
    console.print(
        Panel(
            "[bold]" + "Welcome to Eric's CLI agent :D" + "[/bold]",
            style=NEON_BLUE,
            box=ROUNDED,
        )
    )


def print_assistant(text: str) -> None:
    """
    Print the assistant's reply in a readable way.

    Uses Rich for formatted output. Empty or whitespace-only text
    prints nothing (or a minimal indicator).
    """
    console = Console()
    if not text or not text.strip():
        return
    console.print(f"[bold {NEON_BLUE}]Assistant:[/bold {NEON_BLUE}]")
    console.print(text)

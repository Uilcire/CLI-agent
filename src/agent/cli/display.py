"""Display layer: pretty-print assistant output using Rich."""

from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.box import ROUNDED
from rich.markup import escape
from rich.prompt import Prompt
from rich.text import Text

# Neon blue hex
NEON_BLUE = "#00d4ff"
DeleteChoice = Literal["delete_grant", "delete_no_grant", "cancel"]
# Prompt: "You:" in bold green
PROMPT_STYLE = "bold light_green"


def stream_assistant(events) -> str:
    """
    Consume streaming events and print each piece as it arrives.
    Content accumulates and scrolls naturally (no overwriting).
    Returns the final assistant text.
    """
    console = Console()
    content_parts: list[str] = []
    final_text = ""
    in_content_block = False

    w = console.width
    sep = "-" * max(0, w - len("Assistant: "))
    console.print(f"[bold {NEON_BLUE}]\nAssistant:[/bold {NEON_BLUE}]")
    console.print(sep, style="dim")

    for event_type, data in events:
        if event_type == "content_delta":
            if not in_content_block:
                console.print(Text.from_markup("[dim]thinking[/dim]"))
                in_content_block = True
            content_parts.append(data["delta"])
            console.print(data["delta"], end="")
        elif event_type == "tool_call":
            if in_content_block:
                console.print()
                in_content_block = False
            name, args = data["name"], data["args"]
            args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
            console.print(Text.from_markup(f"⟳ [bold cyan]{escape(str(name))}[/bold cyan]({escape(args_str)})"))
        elif event_type == "tool_result":
            in_content_block = False
        elif event_type == "done":
            final_text = data.get("text", "")
            if in_content_block:
                console.print()
            break

    return final_text


def print_banner() -> None:
    """Print the CLI agent banner on startup (neon blue, rounded border)."""
    console = Console()
    console.print(
        Panel(
            "[bold]" + "欢迎使用 Eric 的 CLI agent :D (版本0.1.0)" + "[/bold]",
            style=NEON_BLUE,
            box=ROUNDED,
        )
    )


def print_assistant(text: str) -> None:
    """Print the assistant's reply. Same format as "You:" — label plus text."""
    console = Console()
    if not text or not text.strip():
        return
    w = console.width
    sep = "-" * max(0, w - len("Assistant: "))
    console.print(f"[bold {NEON_BLUE}]\nAssistant:[/bold {NEON_BLUE}]")
    console.print(f"{sep}\n", style="dim")
    console.print(text)


def prompt_user() -> str:
    """Show "You:" in bold green and return user input."""
    console = Console()
    w = console.width
    result = console.input(f"[{PROMPT_STYLE}]You:[/{PROMPT_STYLE}]\n").strip()
    return result


def confirm_delete(path: str) -> DeleteChoice:
    """
    Show a permission box for deleting a file or directory.
    Returns one of: "delete_grant", "delete_no_grant", "cancel".
    When stdin is not a TTY (e.g. piped input), defaults to cancel.
    """
    import sys
    if not sys.stdin.isatty():
        return "cancel"
    console = Console()
    options = (
        f"[dim]1.[/dim] Delete [cyan]{escape(path)}[/cyan] and grant permission to delete its contents in the future\n"
        f"[dim]2.[/dim] Delete [cyan]{escape(path)}[/cyan] and do not grant future permission\n"
        f"[dim]3.[/dim] Do not delete"
    )
    content = f"Permission to delete?\n\n{options}\n"
    console.print(
        Panel(
            content,
            title="[bold]Confirm Delete[/bold]",
            border_style="yellow",
            box=ROUNDED,
        )
    )
    choice = Prompt.ask(
        "Choose",
        choices=["1", "2", "3"],
        default="3",
    )
    return {"1": "delete_grant", "2": "delete_no_grant", "3": "cancel"}[choice]

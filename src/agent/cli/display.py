"""Display layer: pretty-print assistant output using Rich."""

from rich.console import Console
from rich.panel import Panel
from rich.box import ROUNDED
from rich.text import Text

# Neon blue hex
NEON_BLUE = "#00d4ff"
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
            console.print(Text(f"⟳ [bold cyan]{name}[/bold cyan]({args_str})"))
        elif event_type == "tool_result":
            in_content_block = False
            name, result = data["name"], data["result"]
            preview = result[:200] + "…" if len(result) > 200 else result
            preview = preview.replace("\n", " ")
            console.print(Text(f"← [dim]{name}[/dim]: {preview}"))
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

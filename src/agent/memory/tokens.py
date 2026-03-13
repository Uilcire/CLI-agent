"""Token counting and truncation for memory context assembly."""


def count_tokens(text: str) -> int:
    """Estimate token count. Tries tiktoken, falls back to word-based estimate."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, int(len(text.split()) * 1.3))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens. Returns full text if it fits."""
    if count_tokens(text) <= max_tokens:
        return text
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        return enc.decode(tokens[:max_tokens])
    except Exception:
        # Fallback: truncate by word ratio
        words = text.split()
        keep = max(1, int(max_tokens / 1.3))
        return " ".join(words[:keep])

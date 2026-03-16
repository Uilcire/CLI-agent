"""Web search using Perplexity Search API. Requires PERPLEXITY_API_KEY in env."""

from perplexity import Perplexity


def web_search(query: str, max_results: int = 7) -> str:
    """
    Search the web using Perplexity's Search API.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default: 7).

    Returns:
        Formatted search results (title + URL) or an error message.
    """
    try:
        client = Perplexity()
        search = client.search.create(
            query=[query],
            max_results=max_results,
        )
        lines: list[str] = []
        for query_results in search.results:
            for result in query_results:
                if isinstance(result, tuple):
                    title, url = result[0], result[1] if len(result) > 1 else ""
                elif hasattr(result, "title") and hasattr(result, "url"):
                    title, url = result.title, result.url
                elif isinstance(result, dict):
                    title, url = result.get("title", ""), result.get("url", "")
                else:
                    continue
                lines.append(f"  {title}: {url}")
        if not lines:
            return "No results found."
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

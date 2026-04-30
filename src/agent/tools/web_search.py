"""Web search using Perplexity Search API. Requires PERPLEXITY_API_KEY in env."""

from perplexity import Perplexity


def web_search(
    query: str,
    max_results: int = 7,
    search_recency_filter: str | None = None,
    search_after_date_filter: str | None = None,
    search_before_date_filter: str | None = None,
    last_updated_after_filter: str | None = None,
    last_updated_before_filter: str | None = None,
    search_domain_filter: list[str] | None = None,
) -> str:
    """Search the web using Perplexity's Search API.

    Supports Perplexity date filters.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (default: 7).
        search_recency_filter: One of "day" | "week" | "month" | "year".
            Note: Perplexity docs say it cannot be combined with other date filters.
        search_after_date_filter: Publication date lower bound (MM/DD/YYYY).
        search_before_date_filter: Publication date upper bound (MM/DD/YYYY).
        last_updated_after_filter: Last-updated date lower bound (MM/DD/YYYY).
        last_updated_before_filter: Last-updated date upper bound (MM/DD/YYYY).
        search_domain_filter: Domains/URLs allowlist/denylist. Prefix with "-" to exclude.

    Returns:
        Formatted search results (title + URL + optional date fields) or an error message.
    """

    try:
        client = Perplexity()

        params: dict = {
            "query": [query],
            "max_results": max_results,
        }

        if search_domain_filter:
            params["search_domain_filter"] = search_domain_filter

        if search_recency_filter:
            params["search_recency_filter"] = search_recency_filter
        else:
            # Only apply exact date filters when recency is not used.
            if search_after_date_filter:
                params["search_after_date_filter"] = search_after_date_filter
            if search_before_date_filter:
                params["search_before_date_filter"] = search_before_date_filter
            if last_updated_after_filter:
                params["last_updated_after_filter"] = last_updated_after_filter
            if last_updated_before_filter:
                params["last_updated_before_filter"] = last_updated_before_filter

        search = client.search.create(**params)

        lines: list[str] = []
        # perplexity-py returns search.results as list[query_results]
        for query_results in search.results:
            for result in query_results:
                title = url = ""
                date = last_updated = None

                if isinstance(result, tuple):
                    title, url = result[0], result[1] if len(result) > 1 else ""
                elif hasattr(result, "title") and hasattr(result, "url"):
                    title, url = result.title, result.url
                    date = getattr(result, "date", None)
                    last_updated = getattr(result, "last_updated", None)
                elif isinstance(result, dict):
                    title, url = result.get("title", ""), result.get("url", "")
                    date = result.get("date")
                    last_updated = result.get("last_updated")
                else:
                    continue

                extra = ""
                if date or last_updated:
                    extra = f" (date={date}, last_updated={last_updated})"
                lines.append(f"  {title}: {url}{extra}")

        if not lines:
            return "No results found."
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

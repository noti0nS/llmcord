import asyncio
import logging
from typing import Any

try:
    from duckduckgo_search import DDGS
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("duckduckgo-search is required for /research") from exc


async def search_topics(
    topics: list[str],
    max_results: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Search each topic on DuckDuckGo and return results.

    Returns a dict mapping each topic to a list of search results.
    Each result contains: title, url, snippet.
    """
    results: dict[str, list[dict[str, Any]]] = {}

    for topic in topics:
        topic_results: list[dict[str, Any]] = []
        try:
            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(topic, max_results=max_results))

            search_output = await asyncio.to_thread(_search)
            for result in search_output:
                topic_results.append(
                    {
                        "title": result.get("title", ""),
                        "url": result.get("href", ""),
                        "snippet": result.get("body", ""),
                    }
                )
        except Exception as e:
            logging.warning("Web search failed for topic '%s': %s", topic, e)

        results[topic] = topic_results

    return results

"""Market search and details tools.

This module provides tools for:
- Semantic search over Kalshi markets using LlamaIndex
- Fetching fresh market details from Kalshi API
- Expanding abstract beliefs into market-relevant keywords
"""

import json
from typing import Optional

from anthropic import Anthropic

from config import settings
from models import MarketMatch, ConvictionExtraction
from services.llama_index_service import LlamaIndexService
from services.kalshi_client import KalshiClient, KalshiError
from agent.prompts.expansion import format_expansion_prompt


# Service instances - initialized by init_services()
_llama_service: Optional[LlamaIndexService] = None
_kalshi_client: Optional[KalshiClient] = None
_anthropic_client: Optional[Anthropic] = None


class MarketSearchError(Exception):
    """Error during market search."""
    pass


class MarketNotFoundError(Exception):
    """Market not found by ticker."""
    pass


def init_services(
    llama_service: LlamaIndexService,
    kalshi_client: KalshiClient
) -> None:
    """Initialize service dependencies.

    Must be called before using market tools.

    Args:
        llama_service: Initialized LlamaIndex service
        kalshi_client: Initialized Kalshi client
    """
    global _llama_service, _kalshi_client
    _llama_service = llama_service
    _kalshi_client = kalshi_client


def _get_llama_service() -> LlamaIndexService:
    """Get LlamaIndex service, raising if not initialized."""
    if _llama_service is None:
        raise RuntimeError(
            "LlamaIndex service not initialized. Call init_services() first."
        )
    return _llama_service


def _get_kalshi_client() -> KalshiClient:
    """Get Kalshi client, raising if not initialized."""
    if _kalshi_client is None:
        raise RuntimeError(
            "Kalshi client not initialized. Call init_services() first."
        )
    return _kalshi_client


def _get_anthropic_client() -> Anthropic:
    """Get or create Anthropic client (lazy initialization)."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


async def search_markets(
    query: str,
    n_results: int = 5,
    category: Optional[str] = None
) -> list[MarketMatch]:
    """Search for markets by semantic similarity.

    Uses LlamaIndex vector store to find markets matching the query.
    Returns markets sorted by relevance score.

    Args:
        query: Natural language search query (e.g., "Bitcoin price 100k")
        n_results: Number of results to return (default 5)
        category: Optional category filter (e.g., "Crypto", "Politics")

    Returns:
        List of MarketMatch objects sorted by relevance

    Raises:
        MarketSearchError: If search fails

    Example:
        >>> markets = await search_markets("Trump election", n_results=3)
        >>> for m in markets:
        ...     print(f"{m.ticker}: {m.title} (score: {m.relevance_score:.2f})")
    """
    llama_service = _get_llama_service()

    try:
        results = llama_service.search_markets(
            query=query,
            n_results=n_results,
            category=category,
            only_active=True
        )
        return results
    except Exception as e:
        raise MarketSearchError(f"Market search failed: {e}")


async def get_market_details(ticker: str) -> MarketMatch:
    """Get fresh market details from Kalshi API.

    Fetches live price data directly from Kalshi, bypassing the index.
    Use this when you need current prices for trading.

    Args:
        ticker: Kalshi market ticker (e.g., "PRES-2024-DJT")

    Returns:
        MarketMatch with current prices and data

    Raises:
        MarketNotFoundError: If ticker doesn't exist
        MarketSearchError: If API call fails

    Example:
        >>> market = await get_market_details("PRES-2024-DJT")
        >>> print(f"YES @ {market.yes_price}c, NO @ {market.no_price}c")
    """
    kalshi_client = _get_kalshi_client()

    try:
        market = kalshi_client.get_market(ticker)
        return market
    except KalshiError as e:
        if "not found" in str(e).lower() or "404" in str(e):
            raise MarketNotFoundError(f"Market '{ticker}' not found")
        raise MarketSearchError(f"Failed to fetch market details: {e}")


async def get_market_from_index(ticker: str) -> Optional[MarketMatch]:
    """Get market from index by exact ticker match.

    Faster than API call but prices may be stale.
    Use for quick lookups when current price isn't critical.

    Args:
        ticker: Kalshi market ticker

    Returns:
        MarketMatch if found in index, None otherwise
    """
    llama_service = _get_llama_service()
    return llama_service.get_market_by_ticker(ticker)


async def expand_belief(belief: str) -> dict:
    """Expand an abstract belief into financial implications.

    Uses Claude to convert abstract statements like "Nike shoes are ugly"
    into concrete financial implications and market-relevant keywords.

    Args:
        belief: Abstract belief statement

    Returns:
        Dict with:
        - original_belief: The input belief
        - financial_implications: List of market implications
        - search_keywords: Keywords for market search
        - market_categories: Relevant market categories
        - suggested_position: Suggested YES/NO stance

    Raises:
        MarketSearchError: If expansion fails

    Example:
        >>> result = await expand_belief("Nike shoes are ugly")
        >>> print(result["search_keywords"])
        ['Nike', 'Nike revenue', 'Nike earnings', ...]
    """
    client = _get_anthropic_client()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": format_expansion_prompt(belief)
            }],
            system="You are a financial analyst. Expand beliefs into market implications. Respond with valid JSON only."
        )

        response_text = response.content[0].text.strip()

        # Handle markdown code blocks
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        return json.loads(response_text)

    except json.JSONDecodeError as e:
        raise MarketSearchError(f"Failed to parse expansion response: {e}")
    except Exception as e:
        raise MarketSearchError(f"Belief expansion failed: {e}")


async def expand_and_search(
    conviction: ConvictionExtraction,
    n_results: int = 5
) -> list[MarketMatch]:
    """Expand conviction keywords and search for markets.

    Combines conviction keywords with belief expansion for comprehensive
    market search. Useful when the topic might be abstract.

    Args:
        conviction: Extracted conviction with keywords
        n_results: Number of results to return

    Returns:
        List of MarketMatch objects, deduplicated and sorted by relevance

    Example:
        >>> conviction = ConvictionExtraction(
        ...     has_trading_intent=True,
        ...     topic="Nike losing popularity",
        ...     keywords=["Nike", "shoes"],
        ...     ...
        ... )
        >>> markets = await expand_and_search(conviction)
    """
    if not conviction.has_trading_intent:
        return []

    # Start with direct keyword search
    base_query = " ".join(conviction.keywords)
    if conviction.topic:
        base_query = f"{conviction.topic} {base_query}"

    results = await search_markets(base_query, n_results=n_results * 2)

    # If we have a topic and few results, try expansion
    if conviction.topic and len(results) < n_results:
        try:
            expansion = await expand_belief(conviction.topic)
            expanded_keywords = expansion.get("search_keywords", [])

            if expanded_keywords:
                expanded_query = " ".join(expanded_keywords[:5])
                expanded_results = await search_markets(
                    expanded_query,
                    n_results=n_results
                )

                # Merge results, avoiding duplicates
                seen_tickers = {r.ticker for r in results}
                for r in expanded_results:
                    if r.ticker not in seen_tickers:
                        results.append(r)
                        seen_tickers.add(r.ticker)

        except MarketSearchError:
            # Expansion failed, continue with base results
            pass

    # Sort by relevance and limit
    results.sort(key=lambda x: x.relevance_score, reverse=True)
    return results[:n_results]


async def refresh_market_index() -> int:
    """Refresh the market index from Kalshi.

    Fetches all open markets and rebuilds the vector index.
    This should be called periodically to keep prices/markets current.

    Returns:
        Number of markets indexed

    Raises:
        MarketSearchError: If refresh fails
    """
    llama_service = _get_llama_service()
    kalshi_client = _get_kalshi_client()

    try:
        count = llama_service.refresh_index(kalshi_client)
        return count
    except Exception as e:
        raise MarketSearchError(f"Failed to refresh market index: {e}")


def get_index_stats() -> dict:
    """Get statistics about the market index.

    Returns:
        Dict with count, categories, initialization status
    """
    llama_service = _get_llama_service()
    return llama_service.get_stats()

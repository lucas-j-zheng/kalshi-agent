"""Conviction extraction tool.

This tool analyzes natural language statements and extracts structured
trading intent using Claude or Groq (free alternative). It identifies:
- Whether the statement expresses a prediction
- The topic being predicted
- The side (YES/NO)
- Conviction level (0.0-1.0)
- Relevant keywords for market search
"""

import json
import logging
from typing import Optional, Union, Any

from config import settings
from models import ConvictionExtraction
from agent.prompts.conviction import format_conviction_prompt, CONVICTION_EXAMPLES

logger = logging.getLogger(__name__)


# Lazy initialization - client created on first use
_client: Optional[Any] = None
_provider: Optional[str] = None  # "anthropic" or "groq"


def _get_client() -> tuple[Any, str]:
    """Get or create LLM client (lazy initialization).

    Returns:
        Tuple of (client, provider_name)
    """
    global _client, _provider

    if _client is None:
        # Prefer Anthropic if available, otherwise use Groq (free)
        if settings.anthropic_api_key:
            key = settings.anthropic_api_key
            logger.info(f"Using Anthropic API for conviction analysis (key: {key[:8]}...{key[-4:]})")
            from anthropic import Anthropic
            _client = Anthropic(api_key=key)
            _provider = "anthropic"
        elif settings.groq_api_key:
            key = settings.groq_api_key
            logger.info(f"Using Groq API for conviction analysis (key: {key[:8]}...{key[-4:]})")
            from openai import OpenAI
            import httpx
            _client = OpenAI(
                api_key=key,
                base_url="https://api.groq.com/openai/v1",
                timeout=httpx.Timeout(60.0, connect=10.0),
                max_retries=2
            )
            _provider = "groq"
        else:
            logger.error("No LLM API key configured!")
            raise ValueError(
                "No LLM API key configured. Set either:\n"
                "  - ANTHROPIC_API_KEY (paid)\n"
                "  - GROQ_API_KEY (free - get at https://console.groq.com)"
            )

    return _client, _provider


class ConvictionAnalysisError(Exception):
    """Error during conviction analysis."""
    pass


def _validate_input(statement: str) -> None:
    """Validate input statement.

    Args:
        statement: The user's statement to analyze

    Raises:
        ValueError: If input is invalid
    """
    if not statement:
        raise ValueError("Statement cannot be empty")

    if not isinstance(statement, str):
        raise ValueError("Statement must be a string")

    statement = statement.strip()
    if len(statement) == 0:
        raise ValueError("Statement cannot be empty or whitespace only")

    if len(statement) > 1000:
        raise ValueError(
            f"Statement too long ({len(statement)} chars). Maximum is 1000 characters."
        )


def _validate_extraction(data: dict) -> ConvictionExtraction:
    """Validate and parse extraction response.

    Args:
        data: Parsed JSON response from Claude

    Returns:
        Validated ConvictionExtraction model

    Raises:
        ConvictionAnalysisError: If response is invalid
    """
    # Check required fields
    required_fields = ["has_trading_intent", "reasoning"]
    for field in required_fields:
        if field not in data:
            raise ConvictionAnalysisError(f"Missing required field: {field}")

    # Validate conviction range
    conviction = data.get("conviction", 0.0)
    if not isinstance(conviction, (int, float)):
        raise ConvictionAnalysisError(f"Conviction must be a number, got: {type(conviction)}")
    if not 0.0 <= conviction <= 1.0:
        raise ConvictionAnalysisError(f"Conviction must be 0.0-1.0, got: {conviction}")

    # Validate side if present
    side = data.get("side")
    if side is not None and side not in ("YES", "NO"):
        raise ConvictionAnalysisError(f"Side must be 'YES', 'NO', or null, got: {side}")

    # Ensure keywords is a list
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []

    # Build validated extraction
    return ConvictionExtraction(
        has_trading_intent=bool(data["has_trading_intent"]),
        topic=data.get("topic"),
        side=side,
        conviction=float(conviction),
        timeframe=data.get("timeframe"),
        keywords=keywords,
        reasoning=data["reasoning"]
    )


def _build_messages(statement: str) -> list[dict]:
    """Build message list for Claude API.

    Includes few-shot examples for better extraction quality.

    Args:
        statement: User's statement to analyze

    Returns:
        List of message dicts for Claude API
    """
    messages = []

    # Add few-shot examples (first 3 for efficiency)
    for example in CONVICTION_EXAMPLES[:3]:
        messages.append({
            "role": "user",
            "content": f"Analyze: \"{example['input']}\""
        })
        messages.append({
            "role": "assistant",
            "content": json.dumps(example["output"])
        })

    # Add the actual request
    messages.append({
        "role": "user",
        "content": format_conviction_prompt(statement)
    })

    return messages


async def analyze_conviction(statement: str) -> ConvictionExtraction:
    """Analyze a natural language statement for trading intent.

    Uses Claude or Groq to extract structured trading intent from user statements
    like "I'm confident Bitcoin will hit 100k" or "Trump is definitely winning".

    Args:
        statement: Natural language statement to analyze

    Returns:
        ConvictionExtraction with topic, side, conviction level, keywords

    Raises:
        ValueError: If input is invalid
        ConvictionAnalysisError: If analysis fails

    Example:
        >>> result = await analyze_conviction("I think Bitcoin will hit 100k")
        >>> result.has_trading_intent
        True
        >>> result.topic
        'Bitcoin reaching $100,000'
        >>> result.side
        'YES'
        >>> result.conviction
        0.65
    """
    # Validate input
    _validate_input(statement)

    client, provider = _get_client()
    system_prompt = "You are a trading intent analyzer. Extract structured data from natural language statements about predictions and beliefs. Always respond with valid JSON only, no markdown."

    try:
        if provider == "anthropic":
            # Anthropic API
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=_build_messages(statement),
                system=system_prompt
            )
            response_text = response.content[0].text.strip()
        else:
            # Groq API (OpenAI-compatible)
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(_build_messages(statement))
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # Free, fast, high quality
                max_tokens=1024,
                messages=messages,
                temperature=0.1  # Low temp for consistent JSON
            )
            response_text = response.choices[0].message.content.strip()

        # Handle markdown code blocks if present
        if response_text.startswith("```"):
            # Remove markdown code block
            lines = response_text.split("\n")
            # Remove first and last lines (```json and ```)
            response_text = "\n".join(lines[1:-1])

        # Parse JSON response
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise ConvictionAnalysisError(
                f"Failed to parse LLM response as JSON: {e}\nResponse: {response_text[:200]}"
            )

        # Validate and return
        return _validate_extraction(data)

    except Exception as e:
        if isinstance(e, (ValueError, ConvictionAnalysisError)):
            raise
        logger.error(f"LLM API call failed ({provider}): {type(e).__name__}: {e}")
        raise ConvictionAnalysisError(f"Conviction analysis failed: {type(e).__name__}: {e}")


def analyze_conviction_sync(statement: str) -> ConvictionExtraction:
    """Synchronous version of analyze_conviction.

    Useful for testing or non-async contexts.

    Args:
        statement: Natural language statement to analyze

    Returns:
        ConvictionExtraction with extracted intent
    """
    import asyncio

    # Check if we're already in an async context
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, need to use a different approach
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                analyze_conviction(statement)
            )
            return future.result()
    except RuntimeError:
        # No running loop, we can use asyncio.run directly
        return asyncio.run(analyze_conviction(statement))

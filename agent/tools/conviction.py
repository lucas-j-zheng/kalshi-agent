"""Conviction extraction tool.

This tool analyzes natural language statements and extracts structured
trading intent using Claude. It identifies:
- Whether the statement expresses a prediction
- The topic being predicted
- The side (YES/NO)
- Conviction level (0.0-1.0)
- Relevant keywords for market search
"""

import json
from typing import Optional

from anthropic import Anthropic

from config import settings
from models import ConvictionExtraction
from agent.prompts.conviction import format_conviction_prompt, CONVICTION_EXAMPLES


# Lazy initialization - client created on first use
_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    """Get or create Anthropic client (lazy initialization)."""
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


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

    Uses Claude to extract structured trading intent from user statements
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

    client = _get_client()

    try:
        # Call Claude with JSON mode
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=_build_messages(statement),
            system="You are a trading intent analyzer. Extract structured data from natural language statements about predictions and beliefs. Always respond with valid JSON only, no markdown."
        )

        # Extract response text
        response_text = response.content[0].text.strip()

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
                f"Failed to parse Claude response as JSON: {e}\nResponse: {response_text[:200]}"
            )

        # Validate and return
        return _validate_extraction(data)

    except Exception as e:
        if isinstance(e, (ValueError, ConvictionAnalysisError)):
            raise
        raise ConvictionAnalysisError(f"Conviction analysis failed: {e}")


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

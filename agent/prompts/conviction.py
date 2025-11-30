"""Conviction extraction prompt templates.

This module provides prompts for analyzing user statements and extracting
structured trading intent including topic, side, conviction level, and keywords.
"""

CONVICTION_EXTRACTION_PROMPT = """
Analyze the user's statement and extract trading intent.

User statement: "{user_input}"

Extract the following as JSON:
{{
  "has_trading_intent": boolean,      // Does this express an opinion about a future event?
  "topic": string | null,             // What are they making a prediction about?
  "side": "YES" | "NO" | null,        // Are they saying it WILL or WON'T happen?
  "conviction": float 0.0-1.0,        // How confident are they?
  "timeframe": string | null,         // Any time constraints mentioned?
  "keywords": string[],               // Key terms for market search
  "reasoning": string                 // Brief explanation of your extraction
}}

Conviction scoring guide:
- 0.9-1.0: "definitely", "absolutely", "no way", "100% sure", "guarantee"
- 0.7-0.9: "very confident", "pretty sure", "strongly believe"
- 0.5-0.7: "think", "believe", "probably", "likely"
- 0.3-0.5: "might", "maybe", "possibly", "could"
- 0.0-0.3: "not sure", "uncertain", uncertain language

If the statement is a question, command, or doesn't express a predictive opinion,
set has_trading_intent to false.

Return ONLY valid JSON, no markdown formatting.
"""

CONVICTION_EXAMPLES = [
    # High conviction YES
    {
        "input": "I'm extremely confident Trump will win the election",
        "output": {
            "has_trading_intent": True,
            "topic": "Trump winning 2024 election",
            "side": "YES",
            "conviction": 0.92,
            "timeframe": None,
            "keywords": ["Trump", "win", "election", "2024", "president"],
            "reasoning": "Strong confidence language 'extremely confident' indicates 0.9+ conviction"
        }
    },
    # High conviction NO
    {
        "input": "There's absolutely no way Bitcoin hits 100k this month",
        "output": {
            "has_trading_intent": True,
            "topic": "Bitcoin reaching $100,000",
            "side": "NO",
            "conviction": 0.95,
            "timeframe": "this month",
            "keywords": ["Bitcoin", "BTC", "100k", "price"],
            "reasoning": "'Absolutely no way' indicates very high conviction against"
        }
    },
    # Medium conviction
    {
        "input": "I think the Fed will probably cut rates in December",
        "output": {
            "has_trading_intent": True,
            "topic": "Federal Reserve rate cut",
            "side": "YES",
            "conviction": 0.65,
            "timeframe": "December",
            "keywords": ["Fed", "Federal Reserve", "rate cut", "interest rates", "FOMC"],
            "reasoning": "'think' and 'probably' suggest moderate conviction"
        }
    },
    # Low conviction
    {
        "input": "SpaceX might land Starship successfully, who knows",
        "output": {
            "has_trading_intent": True,
            "topic": "SpaceX Starship landing",
            "side": "YES",
            "conviction": 0.35,
            "timeframe": None,
            "keywords": ["SpaceX", "Starship", "landing", "rocket"],
            "reasoning": "'might' and 'who knows' indicate low conviction"
        }
    },
    # Non-trading statement (question)
    {
        "input": "What markets are available for crypto?",
        "output": {
            "has_trading_intent": False,
            "topic": None,
            "side": None,
            "conviction": 0.0,
            "timeframe": None,
            "keywords": [],
            "reasoning": "This is a question, not a predictive statement"
        }
    },
    # Non-trading statement (command)
    {
        "input": "Show me my portfolio",
        "output": {
            "has_trading_intent": False,
            "topic": None,
            "side": None,
            "conviction": 0.0,
            "timeframe": None,
            "keywords": [],
            "reasoning": "This is a command, not a prediction about future events"
        }
    },
    # High conviction with specific timeframe
    {
        "input": "I guarantee Nvidia will beat earnings next quarter",
        "output": {
            "has_trading_intent": True,
            "topic": "Nvidia earnings beat",
            "side": "YES",
            "conviction": 0.95,
            "timeframe": "next quarter",
            "keywords": ["Nvidia", "NVDA", "earnings", "beat", "revenue"],
            "reasoning": "'guarantee' indicates maximum conviction level"
        }
    },
    # Implicit NO side
    {
        "input": "The Democrats are going to lose the House badly",
        "output": {
            "has_trading_intent": True,
            "topic": "Democrats losing House of Representatives",
            "side": "NO",
            "conviction": 0.82,
            "timeframe": None,
            "keywords": ["Democrats", "House", "Congress", "election", "lose"],
            "reasoning": "'going to lose badly' expresses high confidence in negative outcome for Democrats; side is NO on Democrat win"
        }
    },
    # Casual but confident
    {
        "input": "Dude, obviously Tesla is gonna crush deliveries",
        "output": {
            "has_trading_intent": True,
            "topic": "Tesla delivery numbers",
            "side": "YES",
            "conviction": 0.85,
            "timeframe": None,
            "keywords": ["Tesla", "TSLA", "deliveries", "cars", "EV"],
            "reasoning": "'obviously' and 'gonna crush' indicate strong conviction despite casual tone"
        }
    },
    # Greeting (non-trading)
    {
        "input": "Hey, how's it going?",
        "output": {
            "has_trading_intent": False,
            "topic": None,
            "side": None,
            "conviction": 0.0,
            "timeframe": None,
            "keywords": [],
            "reasoning": "Social greeting with no prediction or trading intent"
        }
    }
]


def format_conviction_prompt(user_input: str) -> str:
    """Format the conviction extraction prompt with user input.

    Args:
        user_input: The user's natural language statement

    Returns:
        Formatted prompt ready for LLM

    Example:
        >>> prompt = format_conviction_prompt("I think Bitcoin will hit 100k")
        >>> assert "I think Bitcoin will hit 100k" in prompt
        >>> assert "{user_input}" not in prompt
    """
    return CONVICTION_EXTRACTION_PROMPT.format(user_input=user_input)

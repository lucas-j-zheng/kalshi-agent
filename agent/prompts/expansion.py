"""Belief expansion prompt templates.

This module provides prompts for expanding abstract beliefs into concrete
financial implications and tradeable market concepts.
"""

BELIEF_EXPANSION_PROMPT = """
Analyze this belief and expand it into financial/market implications.

User belief: "{belief}"

This belief may be abstract (e.g., "Nike shoes are ugly") but could have
implications for prediction markets. Expand it into concrete, tradeable concepts.

Return JSON:
{{
  "original_belief": string,
  "financial_implications": string[],   // How this belief affects markets/outcomes
  "search_keywords": string[],          // Terms to search for relevant markets
  "market_categories": string[],        // Relevant categories (Politics, Crypto, Sports, etc.)
  "suggested_position": string          // Brief suggestion: YES/NO on what type of outcomes
}}

Examples of expansion:
- "Nike shoes are ugly" -> Nike revenue, sales, earnings implications
- "AI is overhyped" -> Tech valuations, AI company performance
- "Housing market will crash" -> Real estate, mortgage rates, construction

Return ONLY valid JSON, no markdown formatting.
"""

EXPANSION_EXAMPLES = [
    {
        "input": "Nike shoes are getting ugly",
        "output": {
            "original_belief": "Nike shoes are getting ugly",
            "financial_implications": [
                "Decreased consumer interest in Nike products",
                "Lower Nike shoe sales",
                "Nike revenue miss vs expectations",
                "Nike stock underperformance",
                "Competitor gains (Adidas, New Balance, On)"
            ],
            "search_keywords": [
                "Nike", "Nike revenue", "Nike earnings", "Nike sales",
                "footwear", "athletic apparel", "sneakers"
            ],
            "market_categories": ["Economics", "Earnings"],
            "suggested_position": "NO on Nike-positive outcomes, YES on Nike revenue miss"
        }
    },
    {
        "input": "AI is completely overhyped",
        "output": {
            "original_belief": "AI is completely overhyped",
            "financial_implications": [
                "AI company valuations may decline",
                "Tech sector correction possible",
                "AI investment may slow down",
                "Nvidia and AI chip demand may disappoint"
            ],
            "search_keywords": [
                "AI", "artificial intelligence", "Nvidia", "tech stocks",
                "machine learning", "OpenAI", "tech bubble"
            ],
            "market_categories": ["Economics", "Technology"],
            "suggested_position": "NO on AI-positive outcomes, YES on tech correction"
        }
    },
    {
        "input": "The housing market is about to crash",
        "output": {
            "original_belief": "The housing market is about to crash",
            "financial_implications": [
                "Home prices will decline significantly",
                "Mortgage rates may spike or banks tighten lending",
                "Construction companies will suffer",
                "Real estate investment trusts underperform"
            ],
            "search_keywords": [
                "housing", "real estate", "home prices", "mortgage",
                "housing crash", "property market", "home sales"
            ],
            "market_categories": ["Economics", "Real Estate"],
            "suggested_position": "YES on housing decline, NO on home price increases"
        }
    },
    {
        "input": "Electric vehicles are the future, gas cars are dead",
        "output": {
            "original_belief": "Electric vehicles are the future, gas cars are dead",
            "financial_implications": [
                "Tesla and EV makers will see increased sales",
                "Traditional automakers may struggle",
                "Oil demand will decrease over time",
                "EV charging infrastructure investment will grow",
                "Battery technology companies will benefit"
            ],
            "search_keywords": [
                "Tesla", "EV", "electric vehicle", "oil", "gasoline",
                "auto sales", "Ford", "GM", "charging", "battery"
            ],
            "market_categories": ["Economics", "Energy", "Automotive"],
            "suggested_position": "YES on EV growth, NO on traditional auto success"
        }
    },
    {
        "input": "TikTok is going to get banned in the US",
        "output": {
            "original_belief": "TikTok is going to get banned in the US",
            "financial_implications": [
                "TikTok user migration to competitors (Instagram Reels, YouTube Shorts)",
                "Meta and Google could benefit from ad revenue shift",
                "ByteDance valuation impact",
                "US-China tech relations tension",
                "Creator economy disruption"
            ],
            "search_keywords": [
                "TikTok", "ban", "ByteDance", "social media",
                "Meta", "Instagram", "Congress", "China"
            ],
            "market_categories": ["Politics", "Technology", "Regulation"],
            "suggested_position": "YES on TikTok ban, YES on competitor growth"
        }
    },
    {
        "input": "Crypto is just gambling, it's going to zero",
        "output": {
            "original_belief": "Crypto is just gambling, it's going to zero",
            "financial_implications": [
                "Bitcoin and major cryptocurrencies will decline",
                "Crypto exchanges will see reduced volume",
                "Blockchain companies will struggle",
                "Regulatory crackdowns more likely",
                "Traditional finance wins over DeFi"
            ],
            "search_keywords": [
                "Bitcoin", "crypto", "cryptocurrency", "Ethereum",
                "Coinbase", "blockchain", "DeFi", "crypto crash"
            ],
            "market_categories": ["Crypto", "Economics"],
            "suggested_position": "NO on crypto price targets, YES on crypto decline"
        }
    },
    {
        "input": "Remote work is here to stay, offices are obsolete",
        "output": {
            "original_belief": "Remote work is here to stay, offices are obsolete",
            "financial_implications": [
                "Commercial real estate values decline",
                "Zoom and remote work tools see sustained demand",
                "Office REIT underperformance",
                "Suburban housing demand increases",
                "Corporate relocation from expensive cities"
            ],
            "search_keywords": [
                "remote work", "office", "commercial real estate",
                "Zoom", "work from home", "REIT", "hybrid work"
            ],
            "market_categories": ["Economics", "Real Estate", "Technology"],
            "suggested_position": "NO on office occupancy recovery, YES on remote work adoption"
        }
    },
    {
        "input": "Climate change will cause more extreme weather events",
        "output": {
            "original_belief": "Climate change will cause more extreme weather events",
            "financial_implications": [
                "Insurance companies face higher payouts",
                "Renewable energy investment increases",
                "Agricultural disruptions and food price volatility",
                "Coastal property values at risk",
                "Climate tech startups benefit"
            ],
            "search_keywords": [
                "climate", "weather", "hurricane", "insurance",
                "renewable energy", "solar", "flooding", "drought"
            ],
            "market_categories": ["Climate", "Economics", "Energy"],
            "suggested_position": "YES on extreme weather events, YES on renewable energy growth"
        }
    }
]


def format_expansion_prompt(belief: str) -> str:
    """Format the belief expansion prompt.

    Args:
        belief: User's belief statement to expand

    Returns:
        Formatted prompt ready for LLM

    Example:
        >>> prompt = format_expansion_prompt("Nike shoes are ugly")
        >>> assert "Nike shoes are ugly" in prompt
        >>> assert "{belief}" not in prompt
    """
    return BELIEF_EXPANSION_PROMPT.format(belief=belief)

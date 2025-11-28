from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum


class Side(str, Enum):
    """Trade side - YES means betting event happens, NO means it won't."""
    YES = "yes"
    NO = "no"


class ConvictionExtraction(BaseModel):
    """Extracted trading intent from natural language input.

    This is the output of the conviction analysis tool that parses
    user statements like "I think Trump will win" into structured data.
    """
    has_trading_intent: bool
    topic: Optional[str] = None
    side: Optional[Literal["YES", "NO"]] = None
    conviction: float = Field(ge=0.0, le=1.0, description="Confidence level 0-1")
    timeframe: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    reasoning: str

    model_config = {"json_schema_extra": {
        "example": {
            "has_trading_intent": True,
            "topic": "Trump winning 2024 election",
            "side": "YES",
            "conviction": 0.85,
            "timeframe": None,
            "keywords": ["Trump", "win", "election", "2024"],
            "reasoning": "User expressed high confidence with 'very confident'"
        }
    }}


class MarketMatch(BaseModel):
    """A Kalshi market returned from search or direct lookup.

    Prices are in cents (1-99) representing probability.
    """
    ticker: str = Field(description="Kalshi market ticker, e.g., 'PRES-2024-DJT'")
    title: str = Field(description="Market question, e.g., 'Will Trump win?'")
    subtitle: str = ""
    category: str = Field(description="Market category, e.g., 'Politics'")
    yes_price: int = Field(ge=1, le=99, description="YES price in cents")
    no_price: int = Field(ge=1, le=99, description="NO price in cents")
    volume: int = Field(ge=0, description="Total contracts traded")
    close_time: datetime = Field(description="When market closes for trading")
    relevance_score: float = Field(
        ge=0.0, le=1.0, default=0.0,
        description="Semantic search relevance (0-1)"
    )

    model_config = {"json_schema_extra": {
        "example": {
            "ticker": "PRES-2024-DJT",
            "title": "Will Donald Trump win the 2024 presidential election?",
            "subtitle": "Resolves Yes if Trump wins",
            "category": "Politics",
            "yes_price": 52,
            "no_price": 48,
            "volume": 1500000,
            "close_time": "2024-11-05T23:59:59Z",
            "relevance_score": 0.94
        }
    }}


class TradeProposal(BaseModel):
    """A proposed trade awaiting user approval.

    Created after user selects a market. Contains all info needed
    for the user to make an informed decision and for execution.
    """
    trade_id: str = Field(description="Unique ID for this proposal (UUID)")
    ticker: str
    title: str
    side: Literal["YES", "NO"]
    contracts: int = Field(gt=0, description="Number of contracts to buy")
    limit_price: int = Field(ge=1, le=99, description="Price per contract in cents")
    total_cost: float = Field(gt=0, description="Total cost in USD")
    max_profit: float = Field(ge=0, description="Maximum profit if correct")
    max_loss: float = Field(gt=0, description="Maximum loss (equals total_cost)")
    conviction: float = Field(ge=0.0, le=1.0, description="User's conviction level")
    market_implied: float = Field(ge=0.0, le=1.0, description="Market implied probability")
    edge: float = Field(description="conviction - market_implied")
    reasoning: str = Field(description="Why this trade was proposed")
    created_at: datetime
    expires_at: datetime = Field(description="When approval token expires")

    model_config = {"json_schema_extra": {
        "example": {
            "trade_id": "abc-123-def-456",
            "ticker": "PRES-2024-DJT",
            "title": "Will Trump win the 2024 election?",
            "side": "YES",
            "contracts": 141,
            "limit_price": 53,
            "total_cost": 74.73,
            "max_profit": 66.27,
            "max_loss": 74.73,
            "conviction": 0.85,
            "market_implied": 0.53,
            "edge": 0.32,
            "reasoning": "User conviction 85% vs market 53%",
            "created_at": "2024-11-25T12:30:00Z",
            "expires_at": "2024-11-25T12:30:30Z"
        }
    }}


class ExecutedTrade(BaseModel):
    """A trade that has been executed on Kalshi.

    Created after user approves and Kalshi confirms the order.
    """
    trade_id: str = Field(description="Original proposal ID")
    order_id: str = Field(description="Kalshi order ID")
    ticker: str
    side: Literal["YES", "NO"]
    contracts: int = Field(gt=0)
    fill_price: int = Field(ge=1, le=99, description="Actual fill price in cents")
    total_cost: float = Field(gt=0)
    executed_at: datetime
    reasoning: str = Field(description="Original reasoning for the trade")

    model_config = {"json_schema_extra": {
        "example": {
            "trade_id": "abc-123-def-456",
            "order_id": "kalshi-ord-789xyz",
            "ticker": "PRES-2024-DJT",
            "side": "YES",
            "contracts": 141,
            "fill_price": 53,
            "total_cost": 74.73,
            "executed_at": "2024-11-25T12:30:15Z",
            "reasoning": "User conviction 85% vs market 53%"
        }
    }}


class Position(BaseModel):
    """An open position in the user's portfolio.

    Tracks current value and unrealized P&L.
    """
    ticker: str
    title: str
    side: Literal["YES", "NO"]
    contracts: int = Field(gt=0)
    avg_price: int = Field(ge=1, le=99, description="Average entry price in cents")
    current_price: int = Field(ge=1, le=99, description="Current market price")
    current_value: float = Field(ge=0, description="Current position value in USD")
    unrealized_pnl: float = Field(description="Unrealized profit/loss in USD")

    model_config = {"json_schema_extra": {
        "example": {
            "ticker": "PRES-2024-DJT",
            "title": "Will Trump win the 2024 election?",
            "side": "YES",
            "contracts": 141,
            "avg_price": 53,
            "current_price": 58,
            "current_value": 81.78,
            "unrealized_pnl": 7.05
        }
    }}


class MarketResearch(BaseModel):
    """Research results for a market including news analysis.

    Generated by the research tool using Tavily + LlamaIndex.
    Used to estimate fair value and provide context.

    Note: This is for future implementation (post-MVP).
    """
    ticker: str
    title: str
    news_summary: str = Field(description="Summary of recent relevant news")
    key_facts: list[str] = Field(description="Bullet points of key information")
    fair_value_estimate: float = Field(
        ge=0.0, le=100.0,
        description="Estimated probability 0-100%"
    )
    market_price: int = Field(ge=1, le=99, description="Current market price in cents")
    edge: float = Field(description="fair_value - market_price (as decimal)")
    confidence: Literal["low", "medium", "high"]
    factors_for: list[str] = Field(description="Reasons event might happen")
    factors_against: list[str] = Field(description="Reasons event might not happen")

    model_config = {"json_schema_extra": {
        "example": {
            "ticker": "SPACEX-STARSHIP",
            "title": "Will SpaceX land Starship?",
            "news_summary": "Recent test showed improved heat shield...",
            "key_facts": [
                "Last test reached 90% of objectives",
                "New heat tiles installed",
                "FAA approval received"
            ],
            "fair_value_estimate": 55.0,
            "market_price": 42,
            "edge": 0.13,
            "confidence": "medium",
            "factors_for": ["Improved heat shield", "FAA cleared"],
            "factors_against": ["Previous failures", "Weather concerns"]
        }
    }}


class FairValueEstimate(BaseModel):
    """Structured LLM output for fair value estimation.

    Used with LlamaIndex structured output parsing to ensure
    consistent responses from the research agent.
    """
    estimated_probability: float = Field(
        ge=0, le=100,
        description="Estimated probability as percentage 0-100"
    )
    confidence: Literal["low", "medium", "high"]
    factors_for: list[str] = Field(
        default_factory=list,
        description="Reasons supporting the event happening"
    )
    factors_against: list[str] = Field(
        default_factory=list,
        description="Reasons against the event happening"
    )
    reasoning: str = Field(description="Explanation of the estimate")

    model_config = {"json_schema_extra": {
        "example": {
            "estimated_probability": 65.0,
            "confidence": "medium",
            "factors_for": ["Strong polling data", "Historical precedent"],
            "factors_against": ["Economic uncertainty", "Low turnout expected"],
            "reasoning": "Based on recent polls and historical patterns..."
        }
    }}

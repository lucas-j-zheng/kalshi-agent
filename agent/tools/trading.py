"""Trading tools for proposing and executing trades.

This module provides tools for:
- Calculating position sizes based on conviction
- Creating trade proposals
- Executing trades with ghost token validation
- Portfolio and balance queries

SECURITY: All trade execution requires ghost token validation.
The agent CANNOT execute trades without explicit user approval.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

from config import settings
from models import TradeProposal, ExecutedTrade, Position
from services.kalshi_client import KalshiClient, KalshiError
from agent.security.ghost_token import (
    GhostTokenValidator,
    GhostTokenError,
)


# Service instances - initialized by init_services()
_kalshi_client: Optional[KalshiClient] = None
_token_validator: Optional[GhostTokenValidator] = None


class TradingError(Exception):
    """Error during trading operations."""
    pass


class InsufficientBalanceError(TradingError):
    """Insufficient balance for trade."""
    pass


class TradeValidationError(TradingError):
    """Trade parameters are invalid."""
    pass


def init_services(
    kalshi_client: KalshiClient,
    token_validator: Optional[GhostTokenValidator] = None
) -> None:
    """Initialize service dependencies.

    Must be called before using trading tools.

    Args:
        kalshi_client: Initialized Kalshi client
        token_validator: Ghost token validator (creates new if not provided)
    """
    global _kalshi_client, _token_validator
    _kalshi_client = kalshi_client
    _token_validator = token_validator or GhostTokenValidator()


def _get_kalshi_client() -> KalshiClient:
    """Get Kalshi client, raising if not initialized."""
    if _kalshi_client is None:
        raise RuntimeError(
            "Kalshi client not initialized. Call init_services() first."
        )
    return _kalshi_client


def _get_token_validator() -> GhostTokenValidator:
    """Get token validator, raising if not initialized."""
    if _token_validator is None:
        raise RuntimeError(
            "Token validator not initialized. Call init_services() first."
        )
    return _token_validator


def calculate_position_size(
    conviction: float,
    edge: float,
    max_usd: Optional[float] = None
) -> float:
    """Calculate recommended position size based on conviction and edge.

    Uses a simple sizing model based on conviction level:
    - 0.9-1.0 conviction: 75-100% of max
    - 0.7-0.9 conviction: 50-75% of max
    - 0.5-0.7 conviction: 25-50% of max
    - <0.5 conviction: 10-25% of max (or skip)

    Edge magnitude provides additional adjustment.

    Args:
        conviction: User's conviction level (0.0-1.0)
        edge: Conviction minus market implied probability
        max_usd: Maximum trade size in USD (default: settings.max_trade_size_usd)

    Returns:
        Recommended position size in USD

    Example:
        >>> size = calculate_position_size(conviction=0.85, edge=0.32)
        >>> print(f"Recommended: ${size:.2f}")
    """
    if max_usd is None:
        max_usd = settings.max_trade_size_usd

    # Base size on conviction level
    if conviction >= 0.9:
        base_pct = 0.875  # 75-100% range, use midpoint
    elif conviction >= 0.7:
        base_pct = 0.625  # 50-75% range
    elif conviction >= 0.5:
        base_pct = 0.375  # 25-50% range
    else:
        base_pct = 0.175  # 10-25% range

    # Adjust for edge magnitude (positive edge increases size)
    edge_adjustment = 1.0
    if edge > 0.20:  # >20% edge
        edge_adjustment = 1.15
    elif edge > 0.10:  # >10% edge
        edge_adjustment = 1.08
    elif edge < 0:  # Negative edge (against the market)
        edge_adjustment = 0.75

    # Calculate final size
    size = max_usd * base_pct * edge_adjustment

    # Ensure within bounds
    size = max(1.0, min(size, max_usd))

    return round(size, 2)


async def propose_trade(
    ticker: str,
    title: str,
    side: Literal["YES", "NO"],
    limit_price: int,
    conviction: float,
    reasoning: str,
    amount_usd: Optional[float] = None,
    close_time: Optional[datetime] = None,
    subtitle: str = ""
) -> TradeProposal:
    """Create a trade proposal for user approval.

    Calculates position sizing, profit/loss scenarios, and edge.
    Registers the proposal with the ghost token validator.

    IMPORTANT: This does NOT execute the trade. User must approve
    via execute_trade() with a valid ghost token.

    Args:
        ticker: Kalshi market ticker
        title: Market title for display
        side: "YES" or "NO"
        limit_price: Price per contract in cents (1-99)
        conviction: User's conviction level (0.0-1.0)
        reasoning: Why this trade was proposed
        amount_usd: Trade amount in USD (calculated if not provided)

    Returns:
        TradeProposal with all details for user review

    Raises:
        TradeValidationError: If parameters are invalid

    Example:
        >>> proposal = await propose_trade(
        ...     ticker="BTC-100K",
        ...     title="Will Bitcoin hit $100k?",
        ...     side="YES",
        ...     limit_price=45,
        ...     conviction=0.75,
        ...     reasoning="User believes BTC rally will continue"
        ... )
        >>> print(f"Trade ID: {proposal.trade_id}")
        >>> print(f"Cost: ${proposal.total_cost:.2f}")
    """
    # Validate inputs
    if not 1 <= limit_price <= 99:
        raise TradeValidationError(f"Limit price must be 1-99 cents, got: {limit_price}")

    if not 0.0 <= conviction <= 1.0:
        raise TradeValidationError(f"Conviction must be 0.0-1.0, got: {conviction}")

    if side not in ("YES", "NO"):
        raise TradeValidationError(f"Side must be 'YES' or 'NO', got: {side}")

    # Calculate market implied probability and edge
    market_implied = limit_price / 100.0  # YES price as probability
    if side == "NO":
        market_implied = 1.0 - market_implied  # NO side: probability it doesn't happen

    edge = conviction - market_implied

    # Calculate position size if not provided
    if amount_usd is None:
        amount_usd = calculate_position_size(conviction, edge)

    # Validate against max trade size
    if amount_usd > settings.max_trade_size_usd:
        raise TradeValidationError(
            f"Amount ${amount_usd:.2f} exceeds max ${settings.max_trade_size_usd}"
        )

    # Calculate contracts
    price_per_contract = limit_price / 100.0  # Convert cents to dollars
    contracts = int(amount_usd / price_per_contract)

    if contracts < 1:
        raise TradeValidationError(
            f"Amount ${amount_usd:.2f} at {limit_price}c yields 0 contracts. Minimum is 1."
        )

    # Recalculate exact cost based on whole contracts
    total_cost = contracts * price_per_contract

    # Calculate profit/loss scenarios
    if side == "YES":
        # YES wins: receive $1 per contract, paid limit_price
        max_profit = contracts * (1.0 - price_per_contract)
    else:
        # NO wins: receive $1 per contract, paid (1 - limit_price)
        max_profit = contracts * price_per_contract

    max_loss = total_cost  # Can lose entire investment

    # Generate trade ID and timestamps
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.ghost_token_ttl)

    # Create proposal
    proposal = TradeProposal(
        trade_id=trade_id,
        ticker=ticker,
        title=title,
        subtitle=subtitle,
        side=side,
        contracts=contracts,
        limit_price=limit_price,
        total_cost=round(total_cost, 2),
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        conviction=conviction,
        market_implied=round(market_implied, 4),
        edge=round(edge, 4),
        reasoning=reasoning,
        created_at=now,
        expires_at=expires_at,
        close_time=close_time
    )

    # Register with ghost token validator
    validator = _get_token_validator()
    validator.register_proposal({
        "trade_id": trade_id,
        "ticker": ticker,
        "side": side,
        "contracts": contracts,
        "limit_price": limit_price,
        "total_cost": total_cost,
        "reasoning": reasoning
    })

    return proposal


async def execute_trade(
    trade_id: str,
    token: str,
    timestamp: int
) -> ExecutedTrade:
    """Execute a trade after ghost token validation.

    This is the ONLY way to execute trades. Requires:
    1. Valid trade_id from a proposal
    2. Ghost token generated client-side on user approval
    3. Timestamp within TTL window

    Args:
        trade_id: Trade proposal ID
        token: Ghost token from client (UUID)
        timestamp: Unix timestamp when token was generated

    Returns:
        ExecutedTrade with order confirmation

    Raises:
        GhostTokenError: If token validation fails
        TradingError: If Kalshi order fails

    Example:
        >>> # After user clicks [APPROVE], frontend generates token
        >>> token = str(uuid.uuid4())
        >>> timestamp = int(time.time())
        >>> executed = await execute_trade(proposal.trade_id, token, timestamp)
        >>> print(f"Order ID: {executed.order_id}")
    """
    validator = _get_token_validator()
    kalshi_client = _get_kalshi_client()

    # Validate and consume token (raises GhostTokenError if invalid)
    trade_details = validator.validate_and_consume(trade_id, token, timestamp)

    # Execute on Kalshi
    try:
        order_response = kalshi_client.place_order(
            ticker=trade_details["ticker"],
            side=trade_details["side"].lower(),  # Kalshi uses lowercase
            contracts=trade_details["contracts"],
            price=trade_details["limit_price"]
        )

        # Extract order info
        order_id = order_response.get("order_id", "unknown")
        fill_price = order_response.get("avg_fill_price", trade_details["limit_price"])

        return ExecutedTrade(
            trade_id=trade_id,
            order_id=order_id,
            ticker=trade_details["ticker"],
            side=trade_details["side"],
            contracts=trade_details["contracts"],
            fill_price=fill_price,
            total_cost=trade_details["total_cost"],
            executed_at=datetime.now(timezone.utc),
            reasoning=trade_details["reasoning"]
        )

    except KalshiError as e:
        # Check for specific errors
        error_msg = str(e).lower()
        if "insufficient" in error_msg or "balance" in error_msg:
            raise InsufficientBalanceError(f"Insufficient balance: {e}")
        raise TradingError(f"Order failed: {e}")


async def cancel_proposal(trade_id: str) -> bool:
    """Cancel a pending trade proposal.

    Called when user clicks [REJECT] or proposal times out.

    Args:
        trade_id: The trade proposal ID

    Returns:
        True if proposal was cancelled, False if not found
    """
    validator = _get_token_validator()
    return validator.cancel_proposal(trade_id)


async def get_pending_proposal(trade_id: str) -> Optional[dict]:
    """Get pending proposal details.

    Args:
        trade_id: The trade proposal ID

    Returns:
        Trade details if found and not expired, None otherwise
    """
    validator = _get_token_validator()
    return validator.get_pending_trade(trade_id)


async def get_portfolio() -> list[Position]:
    """Get current portfolio positions.

    Returns:
        List of Position objects with current values and P&L
    """
    kalshi_client = _get_kalshi_client()
    return kalshi_client.get_positions()


async def get_balance() -> float:
    """Get available balance in USD.

    Returns:
        Balance in USD (converted from cents)
    """
    kalshi_client = _get_kalshi_client()
    return kalshi_client.get_balance()


async def get_order_history(limit: int = 20) -> list[dict]:
    """Get recent order history.

    Args:
        limit: Maximum orders to return

    Returns:
        List of order dictionaries from Kalshi
    """
    kalshi_client = _get_kalshi_client()
    return kalshi_client.get_orders(limit=limit)


def get_pending_trades_count() -> int:
    """Get count of pending trade proposals.

    Returns:
        Number of proposals awaiting approval
    """
    validator = _get_token_validator()
    return validator.pending_count

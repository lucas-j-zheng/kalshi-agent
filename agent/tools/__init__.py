"""Agent tools for conviction analysis, market search, and trading."""

from agent.tools.conviction import (
    analyze_conviction,
    analyze_conviction_sync,
    ConvictionAnalysisError,
)
from agent.tools.markets import (
    search_markets,
    get_market_details,
    get_market_from_index,
    expand_belief,
    expand_and_search,
    refresh_market_index,
    get_index_stats,
    init_services as init_market_services,
    MarketSearchError,
    MarketNotFoundError,
)
from agent.tools.trading import (
    calculate_position_size,
    propose_trade,
    execute_trade,
    cancel_proposal,
    get_pending_proposal,
    get_portfolio,
    get_balance,
    get_order_history,
    get_pending_trades_count,
    init_services as init_trading_services,
    TradingError,
    InsufficientBalanceError,
    TradeValidationError,
)

__all__ = [
    # Conviction
    "analyze_conviction",
    "analyze_conviction_sync",
    "ConvictionAnalysisError",
    # Markets
    "search_markets",
    "get_market_details",
    "get_market_from_index",
    "expand_belief",
    "expand_and_search",
    "refresh_market_index",
    "get_index_stats",
    "init_market_services",
    "MarketSearchError",
    "MarketNotFoundError",
    # Trading
    "calculate_position_size",
    "propose_trade",
    "execute_trade",
    "cancel_proposal",
    "get_pending_proposal",
    "get_portfolio",
    "get_balance",
    "get_order_history",
    "get_pending_trades_count",
    "init_trading_services",
    "TradingError",
    "InsufficientBalanceError",
    "TradeValidationError",
]

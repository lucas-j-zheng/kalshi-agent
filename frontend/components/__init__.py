"""Frontend UI Components.

Visual components for the Kalshi Alpha Agent interface.
"""

from frontend.components.trade_card import (
    render_trade_card_html,
    render_executed_trade_html,
    render_error_card_html,
    render_expired_card_html,
    generate_ghost_token,
    create_trade_card_component,
)

from frontend.components.portfolio_view import (
    render_portfolio_html,
    render_balance_html,
    render_empty_portfolio_html,
    create_portfolio_component,
)

__all__ = [
    # Trade card
    "render_trade_card_html",
    "render_executed_trade_html",
    "render_error_card_html",
    "render_expired_card_html",
    "generate_ghost_token",
    "create_trade_card_component",
    # Portfolio
    "render_portfolio_html",
    "render_balance_html",
    "render_empty_portfolio_html",
    "create_portfolio_component",
]

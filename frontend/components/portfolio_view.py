# -*- coding: utf-8 -*-
"""Portfolio View Component for Kalshi Alpha Agent.

Displays current portfolio positions and account balance.
Shows P&L for each position with color coding.
"""

from typing import List, Optional

import gradio as gr

from models import Position


def format_currency(amount: float, include_sign: bool = False) -> str:
    """Format amount as USD currency."""
    if include_sign:
        if amount >= 0:
            return f"+${amount:.2f}"
        return f"-${abs(amount):.2f}"
    return f"${abs(amount):.2f}"


def format_pnl_color(pnl: float) -> str:
    """Get color for P&L display."""
    if pnl > 0:
        return "#22c55e"  # green
    elif pnl < 0:
        return "#ef4444"  # red
    return "#94a3b8"  # gray


def render_position_row(position: Position) -> str:
    """Render a single position as an HTML row.

    Args:
        position: The position to render

    Returns:
        HTML string for the position row
    """
    pnl_color = format_pnl_color(position.unrealized_pnl)
    side_color = "#3b82f6" if position.side == "YES" else "#f97316"

    # Calculate P&L percentage
    cost_basis = position.contracts * position.avg_price / 100
    pnl_pct = (position.unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0

    return f"""
    <div style="
        background: #1e293b;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
        display: grid;
        grid-template-columns: 2fr 1fr 1fr 1fr;
        gap: 12px;
        align-items: center;
    ">
        <div>
            <div style="font-size: 14px; font-weight: 500; color: #f1f5f9; margin-bottom: 2px;">
                {position.title[:50]}{'...' if len(position.title) > 50 else ''}
            </div>
            <div style="font-size: 11px; color: #64748b;">
                {position.ticker}
                <span style="color: {side_color}; font-weight: 500;">{position.side}</span>
            </div>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 14px; font-weight: 500; color: #f1f5f9;">
                {position.contracts}
            </div>
            <div style="font-size: 11px; color: #64748b;">contracts</div>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 14px; font-weight: 500; color: #f1f5f9;">
                {position.avg_price}c &#x2192; {position.current_price}c
            </div>
            <div style="font-size: 11px; color: #64748b;">avg &#x2192; current</div>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 14px; font-weight: 600; color: {pnl_color};">
                {format_currency(position.unrealized_pnl, include_sign=True)}
            </div>
            <div style="font-size: 11px; color: {pnl_color};">
                {'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%
            </div>
        </div>
    </div>
    """


def render_portfolio_html(
    positions: List[Position],
    total_value: float,
    total_pnl: float,
    balance: float
) -> str:
    """Render the full portfolio view as HTML.

    Args:
        positions: List of current positions
        total_value: Total portfolio value
        total_pnl: Total unrealized P&L
        balance: Available cash balance

    Returns:
        HTML string for the portfolio view
    """
    pnl_color = format_pnl_color(total_pnl)

    # Render position rows
    if positions:
        positions_html = "".join(render_position_row(p) for p in positions)
    else:
        positions_html = """
        <div style="
            text-align: center;
            padding: 40px 20px;
            color: #64748b;
        ">
            <div style="font-size: 32px; margin-bottom: 8px;">&#x1F4ED;</div>
            <div style="font-size: 14px;">No open positions</div>
            <div style="font-size: 12px; margin-top: 4px;">
                Your trades will appear here
            </div>
        </div>
        """

    html = f"""
    <div style="
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e2e8f0;
    ">
        <!-- Header -->
        <div style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #334155;
        ">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 20px;">&#x1F4BC;</span>
                <span style="font-size: 16px; font-weight: 600; color: #f8fafc;">Portfolio</span>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 12px; color: #64748b;">Available Balance</div>
                <div style="font-size: 18px; font-weight: 600; color: #f1f5f9;">
                    ${balance:.2f}
                </div>
            </div>
        </div>

        <!-- Summary Cards -->
        <div style="
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 16px;
        ">
            <div style="
                background: #0f172a;
                border-radius: 8px;
                padding: 12px;
                text-align: center;
            ">
                <div style="font-size: 12px; color: #64748b; margin-bottom: 4px;">Total Value</div>
                <div style="font-size: 20px; font-weight: 600; color: #f1f5f9;">
                    ${total_value:.2f}
                </div>
            </div>
            <div style="
                background: #0f172a;
                border-radius: 8px;
                padding: 12px;
                text-align: center;
            ">
                <div style="font-size: 12px; color: #64748b; margin-bottom: 4px;">Unrealized P&amp;L</div>
                <div style="font-size: 20px; font-weight: 600; color: {pnl_color};">
                    {format_currency(total_pnl, include_sign=True)}
                </div>
            </div>
        </div>

        <!-- Column Headers -->
        {'''
        <div style="
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 1fr;
            gap: 12px;
            padding: 8px 16px;
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        ">
            <div>Market</div>
            <div style="text-align: right;">Size</div>
            <div style="text-align: right;">Price</div>
            <div style="text-align: right;">P&amp;L</div>
        </div>
        ''' if positions else ''}

        <!-- Positions -->
        {positions_html}
    </div>
    """
    return html


def render_balance_html(balance: float, pending_trades: int = 0) -> str:
    """Render a compact balance display.

    Args:
        balance: Available balance in USD
        pending_trades: Number of pending trade proposals

    Returns:
        HTML string for balance display
    """
    pending_html = ""
    if pending_trades > 0:
        pending_html = f"""
        <span style="
            background: #fbbf24;
            color: #78350f;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
            margin-left: 8px;
        ">{pending_trades} pending</span>
        """

    html = f"""
    <div style="
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 8px 16px;
        font-family: system-ui, -apple-system, sans-serif;
    ">
        <span style="font-size: 16px;">&#x1F4B0;</span>
        <span style="font-size: 14px; color: #94a3b8;">Balance:</span>
        <span style="font-size: 16px; font-weight: 600; color: #f1f5f9;">${balance:.2f}</span>
        {pending_html}
    </div>
    """
    return html


def render_empty_portfolio_html() -> str:
    """Render placeholder when portfolio hasn't loaded yet."""
    return """
    <div style="
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 40px 20px;
        text-align: center;
        font-family: system-ui, -apple-system, sans-serif;
        color: #64748b;
    ">
        <div style="font-size: 24px; margin-bottom: 8px;">&#x1F4BC;</div>
        <div style="font-size: 14px;">Loading portfolio...</div>
    </div>
    """


def create_portfolio_component():
    """Create the portfolio view Gradio component.

    Returns:
        Tuple of (container, html_display, refresh_btn)
    """
    with gr.Group() as container:
        # Gradio 6: padding default changed to False; we use inline CSS for padding
        html_display = gr.HTML(
            value=render_empty_portfolio_html(),
            label="Portfolio",
            padding=False,
        )
        refresh_btn = gr.Button(
            "Refresh Portfolio",
            variant="secondary",
            size="sm"
        )

    return container, html_display, refresh_btn

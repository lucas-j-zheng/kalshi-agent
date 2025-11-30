"""Trade Card Component for Kalshi Alpha Agent.

Renders trade proposals as visual cards with approve/reject buttons.
Handles ghost token generation for secure trade execution.

SECURITY: The ghost token is generated CLIENT-SIDE when the user
clicks [APPROVE]. This prevents the agent from forging approvals.
"""

import uuid
import time
from typing import Optional, Tuple
from dataclasses import dataclass

import gradio as gr

from models import TradeProposal, ExecutedTrade


@dataclass
class TradeCardState:
    """State for tracking active trade proposal."""
    proposal: Optional[TradeProposal] = None
    countdown_active: bool = False


def generate_ghost_token() -> Tuple[str, int]:
    """Generate a ghost token for trade approval.

    SECURITY: This function MUST be called client-side (in the frontend)
    when the user clicks the approve button. The agent cannot call this.

    Returns:
        Tuple of (token: str, timestamp: int)
    """
    token = str(uuid.uuid4())
    timestamp = int(time.time())
    return token, timestamp


def format_currency(amount: float) -> str:
    """Format amount as USD currency."""
    if amount >= 0:
        return f"${amount:.2f}"
    return f"-${abs(amount):.2f}"


def format_percentage(value: float, include_sign: bool = True) -> str:
    """Format decimal as percentage."""
    pct = value * 100
    if include_sign and value > 0:
        return f"+{pct:.1f}%"
    return f"{pct:.1f}%"


def calculate_time_remaining(proposal: TradeProposal) -> int:
    """Calculate seconds remaining until proposal expires."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    expires = proposal.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    remaining = (expires - now).total_seconds()
    return max(0, int(remaining))


def render_trade_card_html(proposal: TradeProposal) -> str:
    """Render trade proposal as HTML card.

    Args:
        proposal: The trade proposal to render

    Returns:
        HTML string for the trade card
    """
    # Determine edge color
    edge_color = "#22c55e" if proposal.edge > 0 else "#ef4444"  # green or red
    edge_label = "Favorable" if proposal.edge > 0 else "Unfavorable"
    edge_icon = "&#x2705;" if proposal.edge > 0 else "&#x26A0;&#xFE0F;"

    # Side color
    side_color = "#3b82f6" if proposal.side == "YES" else "#f97316"  # blue or orange

    # Calculate conviction bar width
    conviction_width = int(proposal.conviction * 100)
    market_width = int(proposal.market_implied * 100)

    # Calculate profit percentage
    profit_pct = (proposal.max_profit / proposal.total_cost) * 100 if proposal.total_cost > 0 else 0

    html = f"""
    <div style="
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 24px;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e2e8f0;
        max-width: 500px;
        margin: 10px auto;
    ">
        <!-- Header -->
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px;">
            <span style="font-size: 24px;">&#x1F4CA;</span>
            <span style="font-size: 18px; font-weight: 600; color: #f8fafc;">TRADE PROPOSAL</span>
        </div>

        <!-- Market Title -->
        <div style="
            background: #1e293b;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 16px;
        ">
            <div style="font-size: 14px; color: #94a3b8; margin-bottom: 4px;">Market</div>
            <div style="font-size: 16px; font-weight: 500; color: #f1f5f9;">{proposal.title}</div>
            <div style="font-size: 12px; color: #64748b; margin-top: 4px;">
                {proposal.ticker}
                {f' | Resolves: {proposal.close_time.strftime("%b %d, %Y")}' if proposal.close_time else ''}
            </div>
        </div>

        <!-- Position Details -->
        <div style="
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 16px;
        ">
            <div style="background: #1e293b; border-radius: 8px; padding: 12px;">
                <div style="font-size: 12px; color: #94a3b8;">Position</div>
                <div style="font-size: 20px; font-weight: 600; color: {side_color};">
                    {proposal.side} @ {proposal.limit_price}c
                </div>
            </div>
            <div style="background: #1e293b; border-radius: 8px; padding: 12px;">
                <div style="font-size: 12px; color: #94a3b8;">Contracts</div>
                <div style="font-size: 20px; font-weight: 600; color: #f1f5f9;">{proposal.contracts}</div>
            </div>
        </div>

        <!-- Cost -->
        <div style="
            background: #1e293b;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 16px;
            text-align: center;
        ">
            <div style="font-size: 12px; color: #94a3b8;">Total Cost</div>
            <div style="font-size: 28px; font-weight: 700; color: #f1f5f9;">
                {format_currency(proposal.total_cost)}
            </div>
        </div>

        <!-- Outcomes -->
        <div style="
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 16px;
        ">
            <div style="
                background: rgba(34, 197, 94, 0.1);
                border: 1px solid rgba(34, 197, 94, 0.3);
                border-radius: 8px;
                padding: 12px;
                text-align: center;
            ">
                <div style="font-size: 12px; color: #94a3b8;">If {proposal.side} wins</div>
                <div style="font-size: 18px; font-weight: 600; color: #22c55e;">
                    +{format_currency(proposal.max_profit)}
                </div>
                <div style="font-size: 12px; color: #22c55e;">
                    (+{profit_pct:.0f}%)
                </div>
            </div>
            <div style="
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 8px;
                padding: 12px;
                text-align: center;
            ">
                <div style="font-size: 12px; color: #94a3b8;">If {proposal.side} loses</div>
                <div style="font-size: 18px; font-weight: 600; color: #ef4444;">
                    -{format_currency(proposal.max_loss)}
                </div>
                <div style="font-size: 12px; color: #ef4444;">(-100%)</div>
            </div>
        </div>

        <!-- Conviction vs Market -->
        <div style="
            background: #1e293b;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 16px;
        ">
            <div style="margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-size: 12px; color: #94a3b8;">Your Conviction</span>
                    <span style="font-size: 14px; font-weight: 600; color: #f1f5f9;">{conviction_width}%</span>
                </div>
                <div style="background: #334155; border-radius: 4px; height: 8px; overflow: hidden;">
                    <div style="background: #3b82f6; height: 100%; width: {conviction_width}%; border-radius: 4px;"></div>
                </div>
            </div>
            <div style="margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-size: 12px; color: #94a3b8;">Market Implied</span>
                    <span style="font-size: 14px; font-weight: 600; color: #f1f5f9;">{market_width}%</span>
                </div>
                <div style="background: #334155; border-radius: 4px; height: 8px; overflow: hidden;">
                    <div style="background: #94a3b8; height: 100%; width: {market_width}%; border-radius: 4px;"></div>
                </div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 8px; border-top: 1px solid #334155;">
                <span style="font-size: 14px; color: #94a3b8;">Edge</span>
                <span style="
                    font-size: 16px;
                    font-weight: 600;
                    color: {edge_color};
                    display: flex;
                    align-items: center;
                    gap: 6px;
                ">
                    {format_percentage(proposal.edge)}
                    <span style="font-size: 12px;">{edge_icon} {edge_label}</span>
                </span>
            </div>
        </div>

        <!-- Reasoning -->
        <div style="
            background: #1e293b;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 16px;
        ">
            <div style="font-size: 12px; color: #94a3b8; margin-bottom: 4px;">Reasoning</div>
            <div style="font-size: 14px; color: #cbd5e1; line-height: 1.5;">{proposal.reasoning}</div>
        </div>

        <!-- Expiry Warning -->
        <div style="
            text-align: center;
            padding: 8px;
            background: rgba(251, 191, 36, 0.1);
            border: 1px solid rgba(251, 191, 36, 0.3);
            border-radius: 8px;
            margin-bottom: 8px;
        ">
            <span style="color: #fbbf24;">&#x23F1;&#xFE0F;</span>
            <span style="color: #fbbf24; font-size: 14px; margin-left: 6px;">
                Expires in {calculate_time_remaining(proposal)} seconds
            </span>
        </div>

        <!-- Trade ID (for debugging) -->
        <div style="text-align: center; font-size: 10px; color: #475569;">
            Trade ID: {proposal.trade_id}
        </div>
    </div>
    """
    return html


def render_executed_trade_html(trade: ExecutedTrade) -> str:
    """Render executed trade confirmation as HTML.

    Args:
        trade: The executed trade to render

    Returns:
        HTML string for the confirmation
    """
    # Calculate potential outcomes
    win_value = trade.contracts * 1.00  # $1 per contract if side wins
    profit = win_value - trade.total_cost

    html = f"""
    <div style="
        background: linear-gradient(135deg, #064e3b 0%, #022c22 100%);
        border: 1px solid #10b981;
        border-radius: 12px;
        padding: 24px;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e2e8f0;
        max-width: 500px;
        margin: 10px auto;
    ">
        <!-- Header -->
        <div style="text-align: center; margin-bottom: 20px;">
            <div style="font-size: 48px; margin-bottom: 8px;">&#x2705;</div>
            <div style="font-size: 20px; font-weight: 600; color: #10b981;">TRADE EXECUTED</div>
        </div>

        <!-- Details -->
        <div style="background: rgba(0,0,0,0.2); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                <div>
                    <div style="font-size: 12px; color: #94a3b8;">Side</div>
                    <div style="font-size: 18px; font-weight: 600; color: #f1f5f9;">{trade.side}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #94a3b8;">Fill Price</div>
                    <div style="font-size: 18px; font-weight: 600; color: #f1f5f9;">{trade.fill_price}c</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #94a3b8;">Contracts</div>
                    <div style="font-size: 18px; font-weight: 600; color: #f1f5f9;">{trade.contracts}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #94a3b8;">Total Cost</div>
                    <div style="font-size: 18px; font-weight: 600; color: #f1f5f9;">${trade.total_cost:.2f}</div>
                </div>
            </div>
        </div>

        <!-- Outcome Preview -->
        <div style="background: rgba(0,0,0,0.2); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
            <div style="font-size: 14px; color: #94a3b8; margin-bottom: 8px;">If {trade.side} wins:</div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #cbd5e1;">You receive</span>
                <span style="font-size: 20px; font-weight: 600; color: #10b981;">${win_value:.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
                <span style="color: #cbd5e1;">Profit</span>
                <span style="font-size: 16px; font-weight: 600; color: #10b981;">+${profit:.2f}</span>
            </div>
        </div>

        <!-- Order ID -->
        <div style="text-align: center; font-size: 12px; color: #64748b;">
            Order ID: {trade.order_id}
        </div>
    </div>
    """
    return html


def render_error_card_html(error_message: str) -> str:
    """Render an error message as an HTML card.

    Args:
        error_message: The error message to display

    Returns:
        HTML string for the error card
    """
    html = f"""
    <div style="
        background: linear-gradient(135deg, #7f1d1d 0%, #450a0a 100%);
        border: 1px solid #ef4444;
        border-radius: 12px;
        padding: 24px;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e2e8f0;
        max-width: 500px;
        margin: 10px auto;
        text-align: center;
    ">
        <div style="font-size: 48px; margin-bottom: 12px;">&#x274C;</div>
        <div style="font-size: 18px; font-weight: 600; color: #fca5a5; margin-bottom: 8px;">Trade Failed</div>
        <div style="font-size: 14px; color: #fecaca;">{error_message}</div>
    </div>
    """
    return html


def render_expired_card_html() -> str:
    """Render an expired proposal message.

    Returns:
        HTML string for expired message
    """
    html = """
    <div style="
        background: linear-gradient(135deg, #78350f 0%, #451a03 100%);
        border: 1px solid #f59e0b;
        border-radius: 12px;
        padding: 24px;
        font-family: system-ui, -apple-system, sans-serif;
        color: #e2e8f0;
        max-width: 500px;
        margin: 10px auto;
        text-align: center;
    ">
        <div style="font-size: 48px; margin-bottom: 12px;">&#x23F0;</div>
        <div style="font-size: 18px; font-weight: 600; color: #fcd34d; margin-bottom: 8px;">Proposal Expired</div>
        <div style="font-size: 14px; color: #fde68a;">The approval window has closed. Please request a new trade proposal.</div>
    </div>
    """
    return html


def create_trade_card_component():
    """Create the trade card Gradio component group.

    Returns:
        Tuple of (container, html_display, approve_btn, reject_btn, trade_id_state)
    """
    with gr.Group(visible=False) as container:
        # Gradio 6: padding default changed to False; we use inline CSS for padding
        html_display = gr.HTML(label="Trade Proposal", padding=False)

        with gr.Row():
            approve_btn = gr.Button(
                "APPROVE",
                variant="primary",
                size="lg",
                scale=2
            )
            reject_btn = gr.Button(
                "REJECT",
                variant="secondary",
                size="lg",
                scale=1
            )

        # Hidden state for trade_id
        trade_id_state = gr.State(value=None)

    return container, html_display, approve_btn, reject_btn, trade_id_state

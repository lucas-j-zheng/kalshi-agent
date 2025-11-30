"""Gradio Frontend for Kalshi Alpha Agent.

Provides a chat interface for natural language trading with
visual trade cards and portfolio management.

The frontend orchestrates the flow:
1. User types conviction/belief
2. Agent analyzes intent and finds markets
3. User selects market
4. Agent proposes trade
5. User approves via button click (generates ghost token)
6. Trade executes

SECURITY: Ghost tokens are generated client-side when user
clicks [APPROVE]. The agent cannot forge trade approvals.
"""

import asyncio
import time
import uuid
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

import gradio as gr
import httpx

from config import settings
from models import (
    ConvictionExtraction,
    MarketMatch,
    TradeProposal,
    ExecutedTrade,
    Position,
)
from frontend.components.trade_card import (
    render_trade_card_html,
    render_executed_trade_html,
    render_error_card_html,
    render_expired_card_html,
    generate_ghost_token,
)
from frontend.components.portfolio_view import (
    render_portfolio_html,
    render_balance_html,
    render_empty_portfolio_html,
)


# API Configuration
API_BASE = f"http://localhost:{settings.port}"
API_TIMEOUT = 30.0


# ============================================================
# API CLIENT
# ============================================================

async def api_call(
    method: str,
    endpoint: str,
    json_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """Make an async HTTP call to the API.

    Args:
        method: HTTP method (GET, POST)
        endpoint: API endpoint path
        json_data: Optional JSON body for POST requests

    Returns:
        Response JSON as dictionary

    Raises:
        Exception: On API errors
    """
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        url = f"{API_BASE}{endpoint}"

        if method == "GET":
            response = await client.get(url)
        else:
            response = await client.post(url, json=json_data)

        if response.status_code >= 400:
            error_detail = response.json().get("detail", response.text)
            raise Exception(f"API Error ({response.status_code}): {error_detail}")

        return response.json()


def sync_api_call(
    method: str,
    endpoint: str,
    json_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """Make a sync HTTP call to the API (for Gradio callbacks)."""
    with httpx.Client(timeout=API_TIMEOUT) as client:
        url = f"{API_BASE}{endpoint}"

        if method == "GET":
            response = client.get(url)
        else:
            response = client.post(url, json=json_data)

        if response.status_code >= 400:
            error_detail = response.json().get("detail", response.text)
            raise Exception(f"API Error ({response.status_code}): {error_detail}")

        return response.json()


# ============================================================
# STATE MANAGEMENT
# ============================================================

class AppState:
    """Application state container."""

    def __init__(self):
        self.current_conviction: Optional[ConvictionExtraction] = None
        self.available_markets: List[MarketMatch] = []
        self.selected_market: Optional[MarketMatch] = None
        self.current_proposal: Optional[TradeProposal] = None
        self.last_executed: Optional[ExecutedTrade] = None

    def reset(self):
        """Reset all state."""
        self.current_conviction = None
        self.available_markets = []
        self.selected_market = None
        self.current_proposal = None
        self.last_executed = None

    def to_dict(self) -> Dict:
        """Serialize state to dict for Gradio state."""
        return {
            "conviction": self.current_conviction.model_dump() if self.current_conviction else None,
            "markets": [m.model_dump() for m in self.available_markets],
            "selected_market": self.selected_market.model_dump() if self.selected_market else None,
            "proposal": self.current_proposal.model_dump() if self.current_proposal else None,
            "last_executed": self.last_executed.model_dump() if self.last_executed else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AppState":
        """Deserialize state from dict."""
        state = cls()
        if data.get("conviction"):
            state.current_conviction = ConvictionExtraction(**data["conviction"])
        if data.get("markets"):
            state.available_markets = [MarketMatch(**m) for m in data["markets"]]
        if data.get("selected_market"):
            state.selected_market = MarketMatch(**data["selected_market"])
        if data.get("proposal"):
            state.current_proposal = TradeProposal(**data["proposal"])
        if data.get("last_executed"):
            state.last_executed = ExecutedTrade(**data["last_executed"])
        return state


# ============================================================
# CHAT HANDLERS
# ============================================================

def format_markets_message(markets: List[MarketMatch]) -> str:
    """Format markets list as a chat message."""
    if not markets:
        return "I couldn't find any relevant markets. Try rephrasing your belief."

    lines = ["I found these relevant markets:\n"]
    for i, market in enumerate(markets, 1):
        lines.append(
            f"**{i}. {market.title}**\n"
            f"   - Ticker: `{market.ticker}`\n"
            f"   - Current: YES @ {market.yes_price}c | NO @ {market.no_price}c\n"
            f"   - Volume: {market.volume:,} contracts\n"
            f"   - Relevance: {market.relevance_score*100:.0f}%\n"
        )
    lines.append("\n**Which market would you like to trade?** (Enter the number or ticker)")
    return "\n".join(lines)


def format_conviction_message(conviction: ConvictionExtraction) -> str:
    """Format conviction extraction as a message."""
    if not conviction.has_trading_intent:
        return (
            "I didn't detect a trading prediction in that statement. "
            "Try something like: 'I think Bitcoin will hit $100k' or "
            "'I'm confident the Fed will cut rates'"
        )

    return (
        f"I understand you believe: **{conviction.topic}**\n\n"
        f"- Side: **{conviction.side}**\n"
        f"- Conviction: **{int(conviction.conviction * 100)}%**\n"
        f"- Reasoning: {conviction.reasoning}\n\n"
        f"Let me search for relevant markets..."
    )


def process_message(
    message: str,
    history: List[Dict[str, str]],
    state_dict: Dict
) -> Tuple[List[Dict[str, str]], Dict, str, bool, str, Optional[str]]:
    """Process user message and update state.

    Args:
        message: User's input message
        history: Chat history (Gradio 6 messages format)
        state_dict: Serialized app state

    Returns:
        Tuple of (history, state_dict, trade_card_html, trade_card_visible, trade_id, selected_ticker)
    """
    state = AppState.from_dict(state_dict) if state_dict else AppState()

    # Default returns
    trade_card_html = ""
    trade_card_visible = False
    trade_id = None
    selected_ticker = None

    try:
        # Check if user is selecting a market
        if state.available_markets and not state.selected_market:
            selected = parse_market_selection(message, state.available_markets)
            if selected:
                state.selected_market = selected

                # Add to history (Gradio 6 messages format)
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": f"Great choice! Getting fresh data for **{selected.title}**..."})

                # Get fresh market details
                fresh_data = sync_api_call("POST", "/tools/get_market_details", {
                    "ticker": selected.ticker
                })
                fresh_market = MarketMatch(**fresh_data)
                state.selected_market = fresh_market

                # Create trade proposal
                proposal_data = sync_api_call("POST", "/tools/propose_trade", {
                    "ticker": fresh_market.ticker,
                    "title": fresh_market.title,
                    "side": state.current_conviction.side,
                    "limit_price": fresh_market.yes_price if state.current_conviction.side == "YES" else fresh_market.no_price,
                    "conviction": state.current_conviction.conviction,
                    "reasoning": f"Based on your belief: {state.current_conviction.topic}"
                })
                proposal = TradeProposal(**proposal_data)
                state.current_proposal = proposal

                # Update history with proposal message (replace last assistant message)
                history[-1] = {
                    "role": "assistant",
                    "content": f"Here's my trade proposal for **{fresh_market.title}**.\n\n"
                    f"Review the details below and click **APPROVE** to execute or **REJECT** to cancel."
                }

                # Show trade card
                trade_card_html = render_trade_card_html(proposal)
                trade_card_visible = True
                trade_id = proposal.trade_id

                return history, state.to_dict(), trade_card_html, trade_card_visible, trade_id, None

        # Regular message - analyze conviction
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "Analyzing your statement..."})

        # Call conviction analysis
        conviction_data = sync_api_call("POST", "/tools/analyze_conviction", {
            "statement": message
        })
        conviction = ConvictionExtraction(**conviction_data)
        state.current_conviction = conviction

        if not conviction.has_trading_intent:
            history[-1] = {"role": "assistant", "content": format_conviction_message(conviction)}
            state.reset()
            return history, state.to_dict(), "", False, None, None

        # Update with conviction analysis
        history[-1] = {"role": "assistant", "content": format_conviction_message(conviction)}

        # Search for markets
        search_query = " ".join(conviction.keywords) if conviction.keywords else conviction.topic
        markets_data = sync_api_call("POST", "/tools/search_markets", {
            "query": search_query,
            "n_results": 5
        })
        markets = [MarketMatch(**m) for m in markets_data]
        state.available_markets = markets

        # Add markets message
        history.append({"role": "assistant", "content": format_markets_message(markets)})

        return history, state.to_dict(), "", False, None, None

    except Exception as e:
        error_msg = f"Sorry, an error occurred: {str(e)}"
        if history and history[-1].get("role") == "assistant":
            history[-1] = {"role": "assistant", "content": error_msg}
        else:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": error_msg})
        return history, state.to_dict() if state else {}, "", False, None, None


def parse_market_selection(
    message: str,
    markets: List[MarketMatch]
) -> Optional[MarketMatch]:
    """Parse user's market selection from message.

    Args:
        message: User's selection message
        markets: Available markets

    Returns:
        Selected market or None
    """
    message = message.strip().lower()

    # Try number selection
    try:
        num = int(message)
        if 1 <= num <= len(markets):
            return markets[num - 1]
    except ValueError:
        pass

    # Try ticker match
    for market in markets:
        if market.ticker.lower() in message or message in market.ticker.lower():
            return market

    # Try title keyword match
    for market in markets:
        title_words = market.title.lower().split()
        if any(word in message for word in title_words if len(word) > 3):
            return market

    return None


# ============================================================
# TRADE ACTION HANDLERS
# ============================================================

def handle_approve(
    trade_id: str,
    state_dict: Dict,
    history: List[Dict[str, str]]
) -> Tuple[List[Dict[str, str]], Dict, str, bool, str]:
    """Handle trade approval button click.

    SECURITY: Generates ghost token client-side for secure execution.

    Args:
        trade_id: The proposal trade ID
        state_dict: Current app state
        history: Chat history (Gradio 6 messages format)

    Returns:
        Tuple of (history, state_dict, trade_card_html, visible, trade_id)
    """
    state = AppState.from_dict(state_dict) if state_dict else AppState()

    if not trade_id or not state.current_proposal:
        return history, state.to_dict(), render_error_card_html("No active proposal"), True, None

    try:
        # SECURITY: Generate ghost token client-side
        token, timestamp = generate_ghost_token()

        # Execute trade with ghost token
        result_data = sync_api_call("POST", "/tools/execute_trade", {
            "trade_id": trade_id,
            "token": token,
            "timestamp": timestamp
        })

        executed = ExecutedTrade(**result_data)
        state.last_executed = executed
        state.current_proposal = None

        # Update history
        history.append({
            "role": "assistant",
            "content": f"**Trade Executed Successfully!**\n\n"
            f"- Order ID: `{executed.order_id}`\n"
            f"- Filled: {executed.contracts} {executed.side} @ {executed.fill_price}c\n"
            f"- Total Cost: ${executed.total_cost:.2f}"
        })

        # Reset state for next trade
        state.available_markets = []
        state.selected_market = None
        state.current_conviction = None

        return history, state.to_dict(), render_executed_trade_html(executed), True, None

    except Exception as e:
        error_msg = str(e)

        # Check for specific error types
        if "expired" in error_msg.lower() or "ttl" in error_msg.lower():
            return history, state.to_dict(), render_expired_card_html(), True, None

        return history, state.to_dict(), render_error_card_html(error_msg), True, None


def handle_reject(
    trade_id: str,
    state_dict: Dict,
    history: List[Dict[str, str]]
) -> Tuple[List[Dict[str, str]], Dict, str, bool, str]:
    """Handle trade rejection button click.

    Args:
        trade_id: The proposal trade ID
        state_dict: Current app state
        history: Chat history (Gradio 6 messages format)

    Returns:
        Tuple of (history, state_dict, trade_card_html, visible, trade_id)
    """
    state = AppState.from_dict(state_dict) if state_dict else AppState()

    if trade_id:
        try:
            sync_api_call("POST", "/tools/cancel_proposal", {
                "trade_id": trade_id
            })
        except Exception:
            pass  # Ignore cancellation errors

    # Reset proposal state
    state.current_proposal = None
    state.selected_market = None

    # Add message
    history.append({
        "role": "assistant",
        "content": "Trade cancelled. Would you like to:\n"
        "- Choose a different market from the list above\n"
        "- Express a new trading conviction"
    })

    return history, state.to_dict(), "", False, None


# ============================================================
# PORTFOLIO HANDLERS
# ============================================================

def fetch_portfolio() -> str:
    """Fetch and render portfolio data."""
    try:
        # Fetch portfolio
        portfolio_data = sync_api_call("GET", "/tools/portfolio")
        positions = [Position(**p) for p in portfolio_data.get("positions", [])]
        total_value = portfolio_data.get("total_value", 0.0)
        total_pnl = portfolio_data.get("total_pnl", 0.0)

        # Fetch balance
        balance_data = sync_api_call("GET", "/tools/balance")
        balance = balance_data.get("available_usd", 0.0)

        return render_portfolio_html(positions, total_value, total_pnl, balance)

    except Exception as e:
        return f"""
        <div style="
            background: #1e293b;
            border: 1px solid #ef4444;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            color: #fca5a5;
        ">
            Failed to load portfolio: {str(e)}
        </div>
        """


def fetch_balance() -> str:
    """Fetch and render balance."""
    try:
        data = sync_api_call("GET", "/tools/balance")
        return render_balance_html(
            balance=data.get("available_usd", 0.0),
            pending_trades=data.get("pending_trades", 0)
        )
    except Exception:
        return render_balance_html(0.0, 0)


# ============================================================
# GRADIO APP
# ============================================================

def create_app() -> gr.Blocks:
    """Create the Gradio Blocks application.

    Returns:
        Configured Gradio Blocks app
    """
    with gr.Blocks(
        title="Kalshi Alpha Agent",
    ) as app:
        # State
        app_state = gr.State(value={})
        current_trade_id = gr.State(value=None)

        # Header
        gr.Markdown("""
        # Kalshi Alpha Agent

        Convert your convictions into trades on Kalshi prediction markets.

        **How it works:**
        1. Express your belief (e.g., "I think Bitcoin will hit $100k")
        2. Review the markets I find
        3. Select a market to trade
        4. Approve or reject the proposed trade

        *Every trade requires your explicit approval. I will never trade without your consent.*
        """)

        with gr.Row():
            # Left column - Chat
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    label="Chat",
                    height=500,
                    show_label=False,
                    container=True,
                    # Gradio 6: messages format is now the default (and only option)
                )

                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Express your belief... (e.g., 'I think the Fed will cut rates in December')",
                        show_label=False,
                        scale=4,
                        container=False,
                    )
                    submit_btn = gr.Button("Send", variant="primary", scale=1)

                # Trade card (initially hidden)
                with gr.Group(visible=False) as trade_card_container:
                    trade_card_html = gr.HTML()
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

            # Right column - Portfolio
            with gr.Column(scale=1):
                portfolio_html = gr.HTML(
                    value=render_empty_portfolio_html(),
                    label="Portfolio"
                )
                refresh_portfolio_btn = gr.Button(
                    "Refresh Portfolio",
                    variant="secondary",
                    size="sm"
                )

        # Footer
        gr.Markdown("""
        ---
        *Kalshi Alpha Agent - Built for the MCP 1st Birthday Hackathon*

        **Security Note:** Trade approvals use one-time ghost tokens generated
        when you click APPROVE. The agent cannot execute trades without your
        explicit action.
        """)

        # ============================================================
        # EVENT HANDLERS
        # ============================================================

        def on_submit(message, history, state):
            """Handle message submission."""
            if not message.strip():
                return history, state, "", False, None

            result = process_message(message, history, state)
            return result[0], result[1], result[2], result[3], result[4]

        def on_approve(trade_id, state, history):
            """Handle approve button click."""
            return handle_approve(trade_id, state, history)

        def on_reject(trade_id, state, history):
            """Handle reject button click."""
            return handle_reject(trade_id, state, history)

        # Message submission
        msg_input.submit(
            fn=on_submit,
            inputs=[msg_input, chatbot, app_state],
            outputs=[chatbot, app_state, trade_card_html, trade_card_container, current_trade_id]
        ).then(
            fn=lambda: "",
            outputs=msg_input
        )

        submit_btn.click(
            fn=on_submit,
            inputs=[msg_input, chatbot, app_state],
            outputs=[chatbot, app_state, trade_card_html, trade_card_container, current_trade_id]
        ).then(
            fn=lambda: "",
            outputs=msg_input
        )

        # Trade actions
        approve_btn.click(
            fn=on_approve,
            inputs=[current_trade_id, app_state, chatbot],
            outputs=[chatbot, app_state, trade_card_html, trade_card_container, current_trade_id]
        )

        reject_btn.click(
            fn=on_reject,
            inputs=[current_trade_id, app_state, chatbot],
            outputs=[chatbot, app_state, trade_card_html, trade_card_container, current_trade_id]
        )

        # Portfolio refresh
        refresh_portfolio_btn.click(
            fn=fetch_portfolio,
            outputs=portfolio_html
        )

        # Load portfolio on start
        app.load(
            fn=fetch_portfolio,
            outputs=portfolio_html
        )

    return app


def launch_app(host: str = None, port: int = None):
    """Launch the Gradio application.

    Args:
        host: Host to bind to (default: settings.host)
        port: Port to bind to (default: settings.port + 1)
    """
    # Custom CSS (moved from Blocks to launch in Gradio 6)
    css = """
    .container { max-width: 1200px; margin: auto; }
    .chat-container { min-height: 400px; }
    .trade-card-container { margin: 20px 0; }
    footer { display: none !important; }
    """

    app = create_app()
    app.launch(
        server_name=host or settings.host,
        server_port=port or settings.port + 1,
        share=False,
        css=css,
    )


if __name__ == "__main__":
    launch_app()

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

DEPLOYMENT: This app can run standalone (direct service calls)
or with a backend API (HTTP calls). Set GRADIO_STANDALONE=true
for Spaces deployment.
"""

import asyncio
import logging
import os
import re
import time
import uuid
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

import gradio as gr

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# SERVICE MODE DETECTION
# ============================================================

# Use standalone mode (direct service calls) when:
# - GRADIO_STANDALONE=true (explicit)
# - Running on Spaces (HF_SPACE is set)
# - No backend URL configured
STANDALONE_MODE = (
    os.environ.get("GRADIO_STANDALONE", "").lower() == "true" or
    os.environ.get("SPACE_ID") is not None  # Hugging Face Spaces
)

logger.info(f"Running in {'STANDALONE' if STANDALONE_MODE else 'API'} mode")


# ============================================================
# SERVICE INITIALIZATION (STANDALONE MODE)
# ============================================================

_services_initialized = False

if STANDALONE_MODE:
    from services.kalshi_client import KalshiClient, KalshiError
    from services.llama_index_service import LlamaIndexService
    from agent.security.ghost_token import GhostTokenValidator
    from agent.tools import (
        analyze_conviction as _analyze_conviction,
        search_markets as _search_markets,
        get_market_details as _get_market_details,
        propose_trade as _propose_trade,
        execute_trade as _execute_trade,
        cancel_proposal as _cancel_proposal,
        get_portfolio as _get_portfolio,
        get_balance as _get_balance,
        init_market_services,
        init_trading_services,
    )

    # Global service instances
    _kalshi_client: Optional[KalshiClient] = None
    _llama_service: Optional[LlamaIndexService] = None
    _token_validator: Optional[GhostTokenValidator] = None

    def init_services():
        """Initialize all services for standalone mode."""
        global _kalshi_client, _llama_service, _token_validator, _services_initialized

        if _services_initialized:
            return

        logger.info("Initializing services for standalone mode...")

        try:
            # 1. Initialize Kalshi client
            logger.info("Initializing Kalshi client...")
            _kalshi_client = KalshiClient()
            balance = _kalshi_client.get_balance()
            logger.info(f"Kalshi connected. Balance: ${balance:.2f}")

            # 2. Initialize LlamaIndex service
            logger.info("Initializing LlamaIndex service...")
            _llama_service = LlamaIndexService()
            _llama_service.init_index()

            # 3. Check if index needs population
            stats = _llama_service.get_stats()
            if stats["count"] == 0:
                logger.info("Index empty, fetching markets from Kalshi...")
                all_markets = _kalshi_client.get_all_markets(status="open")
                logger.info(f"Indexing {len(all_markets)} markets...")
                _llama_service.index_markets(all_markets)
                logger.info("Market index populated.")
            else:
                logger.info(f"Index loaded with {stats['count']} markets.")

            # 4. Initialize ghost token validator
            _token_validator = GhostTokenValidator()

            # 5. Wire up tool services
            init_market_services(
                llama_service=_llama_service,
                kalshi_client=_kalshi_client
            )
            init_trading_services(
                kalshi_client=_kalshi_client,
                token_validator=_token_validator
            )

            _services_initialized = True
            logger.info("All services initialized successfully.")

        except Exception as e:
            logger.error(f"Failed to initialize services: {e}")
            raise

    # Initialize on import
    try:
        init_services()
    except Exception as e:
        logger.warning(f"Service initialization failed: {e}")


# ============================================================
# SERVICE CALLS (STANDALONE OR API)
# ============================================================

def call_analyze_conviction(statement: str) -> Dict[str, Any]:
    """Analyze conviction - direct or via API."""
    if STANDALONE_MODE:
        result = asyncio.get_event_loop().run_until_complete(
            _analyze_conviction(statement)
        )
        return result.model_dump()
    else:
        return _api_call("POST", "/tools/analyze_conviction", {"statement": statement})


def call_search_markets(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """Search markets - direct or via API."""
    if STANDALONE_MODE:
        results = asyncio.get_event_loop().run_until_complete(
            _search_markets(query, n_results=n_results)
        )
        return [r.model_dump() for r in results]
    else:
        return _api_call("POST", "/tools/search_markets", {"query": query, "n_results": n_results})


def call_get_market_details(ticker: str) -> Dict[str, Any]:
    """Get market details - direct or via API."""
    if STANDALONE_MODE:
        result = asyncio.get_event_loop().run_until_complete(
            _get_market_details(ticker)
        )
        return result.model_dump()
    else:
        return _api_call("POST", "/tools/get_market_details", {"ticker": ticker})


def call_propose_trade(
    ticker: str,
    title: str,
    side: str,
    limit_price: int,
    conviction: float,
    reasoning: str
) -> Dict[str, Any]:
    """Propose trade - direct or via API."""
    if STANDALONE_MODE:
        result = asyncio.get_event_loop().run_until_complete(
            _propose_trade(
                ticker=ticker,
                title=title,
                side=side,
                limit_price=limit_price,
                conviction=conviction,
                reasoning=reasoning
            )
        )
        return result.model_dump()
    else:
        return _api_call("POST", "/tools/propose_trade", {
            "ticker": ticker,
            "title": title,
            "side": side,
            "limit_price": limit_price,
            "conviction": conviction,
            "reasoning": reasoning
        })


def call_execute_trade(trade_id: str, token: str, timestamp: int) -> Dict[str, Any]:
    """Execute trade - direct or via API."""
    if STANDALONE_MODE:
        result = asyncio.get_event_loop().run_until_complete(
            _execute_trade(trade_id=trade_id, token=token, timestamp=timestamp)
        )
        return result.model_dump()
    else:
        return _api_call("POST", "/tools/execute_trade", {
            "trade_id": trade_id,
            "token": token,
            "timestamp": timestamp
        })


def call_cancel_proposal(trade_id: str) -> Dict[str, Any]:
    """Cancel proposal - direct or via API."""
    if STANDALONE_MODE:
        result = asyncio.get_event_loop().run_until_complete(
            _cancel_proposal(trade_id)
        )
        return {"success": result, "trade_id": trade_id}
    else:
        return _api_call("POST", "/tools/cancel_proposal", {"trade_id": trade_id})


def call_get_portfolio() -> Dict[str, Any]:
    """Get portfolio - direct or via API."""
    if STANDALONE_MODE:
        positions, total_value, total_pnl = asyncio.get_event_loop().run_until_complete(
            _get_portfolio()
        )
        return {
            "positions": [p.model_dump() for p in positions],
            "total_value": total_value,
            "total_pnl": total_pnl
        }
    else:
        return _api_call("GET", "/tools/portfolio")


def call_get_balance() -> Dict[str, Any]:
    """Get balance - direct or via API."""
    if STANDALONE_MODE:
        balance = asyncio.get_event_loop().run_until_complete(_get_balance())
        return {"available_usd": balance, "pending_trades": 0}
    else:
        return _api_call("GET", "/tools/balance")


# ============================================================
# API CLIENT (FALLBACK FOR NON-STANDALONE MODE)
# ============================================================

def _api_call(method: str, endpoint: str, json_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Make HTTP call to backend API."""
    import httpx

    API_BASE = f"http://localhost:{settings.port}"
    API_TIMEOUT = 30.0

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

def parse_ticker_threshold(ticker: str) -> Optional[str]:
    """Extract price threshold from ticker if present.

    Examples:
        KXBTCMAX150-25-DEC31-149999.99 -> $150,000
        KXBTCMAXY-25-DEC31-224999.99 -> $225,000
    """
    # Look for price patterns like 149999.99, 224999.99, etc.
    match = re.search(r'-(\d{5,})\.?\d*$', ticker)
    if match:
        price = float(match.group(1))
        if price > 1000:
            return f"${price/1000:,.0f}k" if price < 1000000 else f"${price:,.0f}"
    return None


def format_market_interpretation(market: MarketMatch) -> str:
    """Generate human-readable interpretation of market odds."""
    yes_prob = market.yes_price
    close_date = market.close_time.strftime("%b %d, %Y")

    # Determine confidence level description with tighter bands
    if yes_prob >= 85:
        confidence = "very likely"
    elif yes_prob >= 65:
        confidence = "likely"
    elif yes_prob >= 55:
        confidence = "leaning YES"
    elif yes_prob >= 45:
        confidence = "toss-up"
    elif yes_prob >= 35:
        confidence = "leaning NO"
    elif yes_prob >= 15:
        confidence = "unlikely"
    else:
        confidence = "very unlikely"

    # Check for unreliable markets
    # - Very low volume (< 500) is always suspect
    # - 50/50 with low volume (< 5000) is likely just default pricing
    is_low_liquidity = market.volume < 500
    is_default_pricing = (yes_prob == 50 and market.no_price == 50 and market.volume < 5000)

    liquidity_warning = " [LOW LIQUIDITY]" if (is_low_liquidity or is_default_pricing) else ""

    return f"{yes_prob}% chance by {close_date} ({confidence}){liquidity_warning}"


def format_markets_message(markets: List[MarketMatch]) -> str:
    """Format markets list as a chat message with interpretation."""
    if not markets:
        return "I couldn't find any relevant markets. Try rephrasing your belief."

    lines = ["**Markets Found:**\n"]

    for i, market in enumerate(markets, 1):
        # Interpret the odds (includes date)
        interpretation = format_market_interpretation(market)

        # Add threshold to title if it's not already mentioned
        title = market.title
        threshold = parse_ticker_threshold(market.ticker)
        if threshold:
            # Check if title already contains a price (has $ in it)
            if "$" not in title:
                title = f"{title} (>{threshold})"

        lines.append(
            f"**{i}. {title}**\n"
            f"   {interpretation} | Vol: {market.volume:,}\n"
        )

    # Find first reliable market for summary
    reliable_market = None
    for m in markets:
        is_reliable = m.volume >= 500 and not (m.yes_price == 50 and m.no_price == 50 and m.volume < 5000)
        if is_reliable:
            reliable_market = m
            break

    if reliable_market:
        lines.append(
            f"\n**Bottom line:** Market #1 has **{reliable_market.yes_price}% odds** of YES.\n"
        )
    else:
        lines.append(
            "\n**Warning:** Low liquidity - these odds may not reflect real market sentiment.\n"
        )

    lines.append("\n**Which market would you like to trade?** (Enter number)")
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
                fresh_data = call_get_market_details(selected.ticker)
                fresh_market = MarketMatch(**fresh_data)
                state.selected_market = fresh_market

                # Create trade proposal
                proposal_data = call_propose_trade(
                    ticker=fresh_market.ticker,
                    title=fresh_market.title,
                    side=state.current_conviction.side,
                    limit_price=fresh_market.yes_price if state.current_conviction.side == "YES" else fresh_market.no_price,
                    conviction=state.current_conviction.conviction,
                    reasoning=f"Based on your belief: {state.current_conviction.topic}"
                )
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

                # Debug logging
                print(f"[DEBUG] Trade proposal created: {trade_id}")
                print(f"[DEBUG] HTML length: {len(trade_card_html)} chars")
                print(f"[DEBUG] Visible: {trade_card_visible}")

                return history, state.to_dict(), trade_card_html, trade_card_visible, trade_id, None

        # Regular message - analyze conviction
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": "Analyzing your statement..."})

        # Call conviction analysis
        conviction_data = call_analyze_conviction(message)
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
        markets_data = call_search_markets(search_query, n_results=5)
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
        result_data = call_execute_trade(trade_id, token, timestamp)

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
            call_cancel_proposal(trade_id)
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
        portfolio_data = call_get_portfolio()
        positions = [Position(**p) for p in portfolio_data.get("positions", [])]
        total_value = portfolio_data.get("total_value", 0.0)
        total_pnl = portfolio_data.get("total_pnl", 0.0)

        # Fetch balance
        balance_data = call_get_balance()
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
        data = call_get_balance()
        return render_balance_html(
            balance=data.get("available_usd", 0.0),
            pending_trades=data.get("pending_trades", 0)
        )
    except Exception:
        return render_balance_html(0.0, 0)


def refresh_markets() -> str:
    """Refresh market index by re-fetching from Kalshi API.

    Returns:
        Status message HTML
    """
    if not STANDALONE_MODE:
        return """
        <div style="color: #fbbf24; padding: 10px; background: #1e293b; border-radius: 8px;">
            Market refresh only available in standalone mode
        </div>
        """

    try:
        logger.info("Refreshing market index...")

        # Use the built-in refresh method which fetches and re-indexes
        count = _llama_service.refresh_index(_kalshi_client)
        logger.info(f"Market index refreshed: {count} markets indexed")

        return f"""
        <div style="color: #22c55e; padding: 10px; background: #1e293b; border-radius: 8px; text-align: center;">
            Refreshed {count:,} markets
        </div>
        """

    except Exception as e:
        logger.error(f"Failed to refresh markets: {e}")
        return f"""
        <div style="color: #ef4444; padding: 10px; background: #1e293b; border-radius: 8px;">
            Failed to refresh: {str(e)}
        </div>
        """


# ============================================================
# GRADIO APP
# ============================================================

def create_app() -> gr.Blocks:
    """Create the Gradio Blocks application.

    Returns:
        Configured Gradio Blocks app
    """
    # Gradio 6: App-level parameters like theme, css moved to launch()
    with gr.Blocks() as app:
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
                    # Gradio 6: type parameter removed; messages format is the only option
                )

                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Express your belief... (e.g., 'I think the Fed will cut rates in December')",
                        show_label=False,
                        scale=4,
                        container=False,
                    )
                    submit_btn = gr.Button("Send", variant="primary", scale=1)

                # Trade card section - HTML is always visible, buttons hidden until proposal
                gr.Markdown("---")
                gr.Markdown("### Trade Proposal")
                trade_card_html = gr.HTML(value="<div style='color: #64748b; text-align: center; padding: 20px;'>Express a belief above to generate a trade proposal</div>")
                with gr.Row(visible=False) as trade_buttons_row:
                    approve_btn = gr.Button(
                        "APPROVE",
                        variant="primary",
                        size="lg",
                        scale=2,
                    )
                    reject_btn = gr.Button(
                        "REJECT",
                        variant="secondary",
                        size="lg",
                        scale=1,
                    )

            # Right column - Portfolio
            with gr.Column(scale=1):
                # Gradio 6: padding default changed to False; we use inline CSS for padding
                portfolio_html = gr.HTML(
                    value=render_empty_portfolio_html(),
                    label="Portfolio",
                    padding=False,
                )
                refresh_portfolio_btn = gr.Button(
                    "Refresh Portfolio",
                    variant="secondary",
                    size="sm"
                )

                gr.Markdown("---")
                gr.Markdown("### Market Index")
                market_status_html = gr.HTML(
                    value="<div style='color: #64748b; padding: 10px; text-align: center;'>Market index loaded</div>"
                )
                refresh_markets_btn = gr.Button(
                    "Refresh Markets",
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
                return history, state, "", gr.Row(visible=False), None

            result = process_message(message, history, state)
            # result = (history, state_dict, trade_card_html, visible, trade_id, _)
            visible = result[3]
            html_content = result[2]

            # Debug logging
            print(f"[DEBUG on_submit] visible={visible}, html_len={len(html_content) if html_content else 0}")

            return (
                result[0],  # history
                result[1],  # state
                html_content,  # trade_card_html content (string)
                gr.Row(visible=visible),  # trade_buttons_row visibility
                result[4],  # trade_id
            )

        def on_approve(trade_id, state, history):
            """Handle approve button click."""
            result = handle_approve(trade_id, state, history)
            # result = (history, state_dict, trade_card_html, visible, trade_id)
            visible = result[3]
            return (
                result[0],  # history
                result[1],  # state
                result[2],  # trade_card_html content (string)
                gr.Row(visible=visible),  # trade_buttons_row visibility
                result[4],  # trade_id
            )

        def on_reject(trade_id, state, history):
            """Handle reject button click."""
            result = handle_reject(trade_id, state, history)
            # result = (history, state_dict, trade_card_html, visible, trade_id)
            visible = result[3]
            return (
                result[0],  # history
                result[1],  # state
                result[2],  # trade_card_html content (string)
                gr.Row(visible=visible),  # trade_buttons_row visibility
                result[4],  # trade_id
            )

        # Message submission
        msg_input.submit(
            fn=on_submit,
            inputs=[msg_input, chatbot, app_state],
            outputs=[chatbot, app_state, trade_card_html, trade_buttons_row, current_trade_id]
        ).then(
            fn=lambda: "",
            outputs=msg_input
        )

        submit_btn.click(
            fn=on_submit,
            inputs=[msg_input, chatbot, app_state],
            outputs=[chatbot, app_state, trade_card_html, trade_buttons_row, current_trade_id]
        ).then(
            fn=lambda: "",
            outputs=msg_input
        )

        # Trade actions
        approve_btn.click(
            fn=on_approve,
            inputs=[current_trade_id, app_state, chatbot],
            outputs=[chatbot, app_state, trade_card_html, trade_buttons_row, current_trade_id]
        )

        reject_btn.click(
            fn=on_reject,
            inputs=[current_trade_id, app_state, chatbot],
            outputs=[chatbot, app_state, trade_card_html, trade_buttons_row, current_trade_id]
        )

        # Portfolio refresh
        refresh_portfolio_btn.click(
            fn=fetch_portfolio,
            outputs=portfolio_html
        )

        # Markets refresh
        refresh_markets_btn.click(
            fn=refresh_markets,
            outputs=market_status_html
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
    # Gradio 6: App-level parameters (css, theme, js, head) moved from Blocks to launch()
    css = """
    .container { max-width: 1200px; margin: auto; }
    .chat-container { min-height: 400px; }
    .trade-card-container { margin: 20px 0; }
    footer { display: none !important; }
    """

    app = create_app()
    # Gradio 6: title can be set via head parameter or theme
    # show_api replaced with footer_links parameter
    app.launch(
        server_name=host or settings.host,
        server_port=port or settings.port + 1,
        share=False,
        css=css,
        # Gradio 6: Use footer_links instead of show_api
        # footer_links=["gradio", "settings"],  # Omit "api" to hide API link
    )


if __name__ == "__main__":
    launch_app()

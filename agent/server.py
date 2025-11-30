"""MCP Server for Kalshi Alpha Agent.

FastAPI application exposing all trading tools as HTTP endpoints.
Handles service initialization, request validation, and error handling.

Endpoints:
- POST /tools/analyze_conviction - Extract trading intent from statements
- POST /tools/search_markets - Semantic market search
- POST /tools/get_market_details - Fetch live prices
- POST /tools/propose_trade - Create trade proposal
- POST /tools/execute_trade - Execute with ghost token
- POST /tools/cancel_proposal - Cancel pending proposal
- GET  /tools/portfolio - Get positions
- GET  /tools/balance - Get account balance
- GET  /mcp/tools - MCP tool definitions
- GET  /health - Service health check
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, Literal
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import settings
from models import (
    ConvictionExtraction,
    MarketMatch,
    TradeProposal,
    ExecutedTrade,
    Position,
)
from services.kalshi_client import KalshiClient, KalshiError
from services.llama_index_service import LlamaIndexService
from agent.security.ghost_token import GhostTokenValidator, GhostTokenError
from agent.tools import (
    analyze_conviction,
    ConvictionAnalysisError,
    search_markets,
    get_market_details,
    expand_and_search,
    refresh_market_index,
    get_index_stats,
    init_market_services,
    MarketSearchError,
    MarketNotFoundError,
    propose_trade,
    execute_trade,
    cancel_proposal,
    get_portfolio,
    get_balance,
    get_pending_trades_count,
    init_trading_services,
    TradingError,
    InsufficientBalanceError,
    TradeValidationError,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# REQUEST MODELS
# ============================================================

class ConvictionRequest(BaseModel):
    """Request to analyze a statement for trading intent."""
    statement: str = Field(..., min_length=1, max_length=1000)

    model_config = {
        "json_schema_extra": {
            "examples": [{"statement": "I think Trump will win the election"}]
        }
    }


class SearchMarketsRequest(BaseModel):
    """Request to search for markets."""
    query: str = Field(..., min_length=1, max_length=500)
    n_results: int = Field(default=5, ge=1, le=20)
    category: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"query": "Bitcoin 100k", "n_results": 5}]
        }
    }


class MarketDetailsRequest(BaseModel):
    """Request to get fresh market details."""
    ticker: str = Field(..., min_length=1, max_length=50)


class ProposeTradeRequest(BaseModel):
    """Request to create a trade proposal."""
    ticker: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=500)
    side: Literal["YES", "NO"]
    limit_price: int = Field(..., ge=1, le=99)
    conviction: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=1, max_length=1000)
    amount_usd: Optional[float] = Field(default=None, ge=1.0, le=10000.0)

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "ticker": "BTC-100K",
                "title": "Will Bitcoin hit $100k?",
                "side": "YES",
                "limit_price": 45,
                "conviction": 0.75,
                "reasoning": "Strong technical indicators"
            }]
        }
    }


class ExecuteTradeRequest(BaseModel):
    """Request to execute an approved trade."""
    trade_id: str = Field(..., min_length=36, max_length=36)
    token: str = Field(..., min_length=36, max_length=36)
    timestamp: int = Field(..., ge=0)

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "trade_id": "550e8400-e29b-41d4-a716-446655440000",
                "token": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "timestamp": 1732567815
            }]
        }
    }


class CancelProposalRequest(BaseModel):
    """Request to cancel a pending proposal."""
    trade_id: str = Field(..., min_length=36, max_length=36)


class ExpandAndSearchRequest(BaseModel):
    """Request to expand conviction and search markets."""
    conviction: ConvictionExtraction


# ============================================================
# RESPONSE MODELS
# ============================================================

class PortfolioResponse(BaseModel):
    """Portfolio positions response."""
    positions: list[Position]
    total_value: float
    total_pnl: float


class BalanceResponse(BaseModel):
    """Account balance response."""
    available_usd: float
    pending_trades: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    kalshi_connected: bool
    index_ready: bool
    markets_indexed: int
    pending_proposals: int
    timestamp: datetime


class RefreshResponse(BaseModel):
    """Index refresh response."""
    success: bool
    markets_indexed: int
    duration_seconds: float


class CancelResponse(BaseModel):
    """Proposal cancellation response."""
    success: bool
    trade_id: str


class ToolDefinition(BaseModel):
    """MCP tool definition."""
    name: str
    description: str
    parameters: dict


class MCPToolsResponse(BaseModel):
    """MCP tools listing response."""
    tools: list[ToolDefinition]


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
    code: str


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - initialize and cleanup services."""
    logger.info("Starting Kalshi Alpha Agent server...")

    # Initialize services
    try:
        # 1. Initialize Kalshi client
        logger.info("Initializing Kalshi client...")
        app.state.kalshi_client = KalshiClient()

        # Test connection
        balance = app.state.kalshi_client.get_balance()
        logger.info(f"Kalshi connected. Balance: ${balance:.2f}")

        # 2. Initialize LlamaIndex service
        logger.info("Initializing LlamaIndex service...")
        app.state.llama_service = LlamaIndexService()
        app.state.llama_service.init_index()

        # 3. Check if index needs population
        stats = app.state.llama_service.get_stats()
        if stats["count"] == 0:
            logger.info("Index empty, fetching markets from Kalshi...")
            all_markets = app.state.kalshi_client.get_all_markets(status="open")
            logger.info(f"Indexing {len(all_markets)} markets...")
            app.state.llama_service.index_markets(all_markets)
            logger.info("Market index populated.")
        else:
            logger.info(f"Index loaded with {stats['count']} markets.")

        # 4. Initialize ghost token validator
        app.state.token_validator = GhostTokenValidator()

        # 5. Wire up tool services
        init_market_services(
            llama_service=app.state.llama_service,
            kalshi_client=app.state.kalshi_client
        )
        init_trading_services(
            kalshi_client=app.state.kalshi_client,
            token_validator=app.state.token_validator
        )

        app.state.initialized = True
        logger.info("All services initialized successfully.")

    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        app.state.initialized = False
        # Don't raise - allow server to start for health checks
        # raise

    yield  # Application runs here

    # Cleanup
    logger.info("Shutting down server...")
    if hasattr(app.state, 'kalshi_client') and app.state.kalshi_client:
        # Cleanup if needed
        pass
    logger.info("Server shutdown complete.")


# ============================================================
# CREATE APPLICATION
# ============================================================

app = FastAPI(
    title="Kalshi Alpha Agent",
    description="Trading assistant that converts convictions into human-approved trades",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HEALTH CHECK (Available even before full initialization)
# ============================================================

@app.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """Health check endpoint for monitoring.

    Returns service status and readiness information.
    """
    kalshi_connected = False
    index_ready = False
    markets_indexed = 0
    pending_proposals = 0

    # Check Kalshi connection
    try:
        if hasattr(request.app.state, 'kalshi_client') and request.app.state.kalshi_client:
            request.app.state.kalshi_client.get_balance()
            kalshi_connected = True
    except Exception:
        pass

    # Check index status
    try:
        if hasattr(request.app.state, 'llama_service') and request.app.state.llama_service:
            stats = request.app.state.llama_service.get_stats()
            markets_indexed = stats.get("count", 0)
            index_ready = markets_indexed > 0
    except Exception:
        pass

    # Check pending proposals
    try:
        if hasattr(request.app.state, 'token_validator') and request.app.state.token_validator:
            pending_proposals = request.app.state.token_validator.pending_count
    except Exception:
        pass

    # Determine overall status
    if kalshi_connected and index_ready:
        status = "healthy"
    elif kalshi_connected or index_ready:
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        kalshi_connected=kalshi_connected,
        index_ready=index_ready,
        markets_indexed=markets_indexed,
        pending_proposals=pending_proposals,
        timestamp=datetime.now(timezone.utc)
    )


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def require_initialized(app_state) -> None:
    """Raise error if services not initialized."""
    if not getattr(app_state, 'initialized', False):
        raise HTTPException(
            status_code=503,
            detail="Server not fully initialized. Try again shortly."
        )


# ============================================================
# SERVER RUNNER
# ============================================================

def run_server(host: str = None, port: int = None):
    """Run the FastAPI server with uvicorn.

    Args:
        host: Host to bind to (default: settings.host)
        port: Port to bind to (default: settings.port)
    """
    import uvicorn

    uvicorn.run(
        "agent.server:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )


if __name__ == "__main__":
    run_server()

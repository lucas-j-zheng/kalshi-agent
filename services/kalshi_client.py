"""Kalshi API client with RSA-PSS authentication.

Handles all interactions with the Kalshi prediction market:
- Market data (list, search, details)
- Portfolio (balance, positions)
- Trading (place orders, cancel)
"""

import httpx
import time
import base64
from datetime import datetime, timezone
from typing import Optional
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from config import settings
from models import MarketMatch, Position


class KalshiError(Exception):
    """Base exception for Kalshi API errors."""
    pass


class KalshiAuthError(KalshiError):
    """Authentication failed - check API key and private key."""
    pass


class KalshiClient:
    """Client for Kalshi API with RSA-PSS authentication.

    Handles all interactions with the Kalshi prediction market:
    - Market data (list, search, details)
    - Portfolio (balance, positions)
    - Trading (place orders, cancel)

    Example:
        with KalshiClient() as client:
            balance = client.get_balance()
            markets = client.get_markets(limit=10)
    """

    def __init__(self):
        self.api_base = settings.kalshi_api_host
        self.key_id = settings.kalshi_api_key_id
        self._private_key = None
        self._client = httpx.Client(timeout=30.0)
        self._load_private_key()

    def _load_private_key(self):
        """Load RSA private key from file."""
        key_bytes = settings.get_private_key()
        self._private_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
            backend=default_backend()
        )

    def _sign_request(self, method: str, path: str, timestamp: int) -> str:
        """Sign a request using RSA-PSS with SHA256.

        Kalshi requires: signature = RSA_PSS_SIGN(timestamp + method + path)
        IMPORTANT: Strip query params from path before signing!

        Args:
            method: HTTP method (GET, POST, DELETE)
            path: API path including /trade-api/v2 prefix
            timestamp: Timestamp in milliseconds

        Returns:
            Base64 encoded signature
        """
        # Strip query params from path
        path_without_query = path.split('?')[0]
        message = f"{timestamp}{method}{path_without_query}".encode('utf-8')

        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    def _get_headers(self, method: str, path: str) -> dict:
        """Generate authenticated headers for API request.

        Args:
            method: HTTP method
            path: API path

        Returns:
            Headers dict with auth credentials
        """
        timestamp = int(time.time() * 1000)  # Kalshi uses milliseconds
        signature = self._sign_request(method, path, timestamp)

        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _request(self, method: str, endpoint: str, json: dict = None) -> dict:
        """Make authenticated request to Kalshi API.

        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint (without /trade-api/v2 prefix)
            json: Request body for POST, or query params for GET

        Returns:
            Parsed JSON response

        Raises:
            KalshiAuthError: On 401 authentication failure
            KalshiError: On other API errors
        """
        path = f"/trade-api/v2{endpoint}"
        url = f"{self.api_base.rstrip('/trade-api/v2')}{path}"
        headers = self._get_headers(method, path)

        try:
            if method == "GET":
                response = self._client.get(url, headers=headers, params=json)
            elif method == "POST":
                response = self._client.post(url, headers=headers, json=json)
            elif method == "DELETE":
                response = self._client.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code == 401:
                raise KalshiAuthError(
                    "Authentication failed - check API key and private key"
                )

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            raise KalshiError(
                f"API error {e.response.status_code}: {e.response.text}"
            )
        except httpx.RequestError as e:
            raise KalshiError(f"Request failed: {str(e)}")

    # =========================================================================
    # Portfolio Methods
    # =========================================================================

    def get_balance(self) -> float:
        """Get available balance in USD.

        Returns:
            Available balance as float in USD
        """
        response = self._request("GET", "/portfolio/balance")
        # Kalshi returns balance in cents
        balance_cents = response.get("balance", 0)
        return balance_cents / 100.0

    def get_positions(self) -> list[Position]:
        """Get current portfolio positions with P&L.

        Returns:
            List of Position objects with current values
        """
        response = self._request("GET", "/portfolio/positions")
        positions_data = response.get("market_positions", [])

        positions = []
        for pos in positions_data:
            ticker = pos["ticker"]
            contracts = abs(pos.get("position", 0))

            # Skip closed positions (0 contracts)
            if contracts == 0:
                continue

            # Get current price for P&L calculation
            try:
                market = self.get_market(ticker)
                current_price = (
                    market.yes_price if pos.get("position", 0) > 0
                    else market.no_price
                )
            except KalshiError:
                current_price = 50  # Default if can't fetch

            avg_price = pos.get("average_price", 50)

            # Calculate value and P&L
            current_value = contracts * current_price / 100
            cost_basis = contracts * avg_price / 100
            unrealized_pnl = current_value - cost_basis

            positions.append(Position(
                ticker=ticker,
                title=pos.get("market_title", ticker),
                side="YES" if pos.get("position", 0) > 0 else "NO",
                contracts=contracts,
                avg_price=avg_price,
                current_price=current_price,
                current_value=current_value,
                unrealized_pnl=unrealized_pnl
            ))

        return positions

    # =========================================================================
    # Market Methods
    # =========================================================================

    def get_markets(
        self,
        status: str = "open",
        limit: int = 1000,
        cursor: str = None,
        series_ticker: str = None,
        event_ticker: str = None
    ) -> list[dict]:
        """Get list of markets from Kalshi.

        Args:
            status: "open", "closed", or "settled"
            limit: Max markets to return (max 1000)
            cursor: Pagination cursor
            series_ticker: Filter by series
            event_ticker: Filter by event

        Returns:
            List of market dictionaries
        """
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker

        response = self._request("GET", "/markets", json=params)
        return response.get("markets", [])

    def get_all_markets(self, status: str = "open") -> list[dict]:
        """Get all markets, handling pagination.

        Args:
            status: "open", "closed", or "settled"

        Returns:
            Complete list of markets
        """
        all_markets = []
        cursor = None

        while True:
            params = {
                "status": status,
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor

            response = self._request("GET", "/markets", json=params)

            markets = response.get("markets", [])
            all_markets.extend(markets)

            cursor = response.get("cursor")
            if not cursor or len(markets) < 1000:
                break

        return all_markets

    def get_market(self, ticker: str) -> MarketMatch:
        """Get single market by ticker with current prices.

        Args:
            ticker: Market ticker (e.g., "PRES-2024-DJT")

        Returns:
            MarketMatch with current data

        Raises:
            KalshiError: If market not found
        """
        response = self._request("GET", f"/markets/{ticker}")
        market = response.get("market", {})

        # Parse close_time - handle different formats
        close_time_str = market.get("close_time", "")
        try:
            close_time = datetime.fromisoformat(
                close_time_str.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            close_time = datetime.now(timezone.utc)

        # Use ASK prices (what you pay to buy), not BID prices (what you get to sell)
        # This ensures limit orders fill immediately
        yes_price = market.get("yes_ask", 50) or market.get("yes_bid", 50) or 50
        no_price = market.get("no_ask", 50) or market.get("no_bid", 50) or 50
        yes_price = max(1, min(99, yes_price))
        no_price = max(1, min(99, no_price))

        return MarketMatch(
            ticker=market["ticker"],
            title=market.get("title", ""),
            subtitle=market.get("subtitle", ""),
            category=market.get("category", ""),
            yes_price=yes_price,
            no_price=no_price,
            volume=market.get("volume", 0),
            close_time=close_time,
            relevance_score=0.0  # Not from search
        )

    # =========================================================================
    # Trading Methods
    # =========================================================================

    def place_order(
        self,
        ticker: str,
        side: str,
        contracts: int,
        price: int,
        order_type: str = "limit"
    ) -> dict:
        """Place an order on Kalshi.

        Args:
            ticker: Market ticker
            side: "yes" or "no"
            contracts: Number of contracts
            price: Limit price in cents (1-99)
            order_type: "limit" or "market"

        Returns:
            Order response with order_id, status, fills

        Raises:
            ValueError: If inputs are invalid
            KalshiError: If order fails
        """
        # Validate inputs
        if side.lower() not in ("yes", "no"):
            raise ValueError(f"Side must be 'yes' or 'no', got: {side}")
        if not 1 <= price <= 99:
            raise ValueError(f"Price must be 1-99 cents, got: {price}")
        if contracts < 1:
            raise ValueError(f"Contracts must be >= 1, got: {contracts}")

        order_data = {
            "ticker": ticker,
            "action": "buy",
            "side": side.lower(),
            "count": contracts,
            "type": order_type,
        }

        if order_type == "limit":
            price_key = "yes_price" if side.lower() == "yes" else "no_price"
            order_data[price_key] = price

        response = self._request("POST", "/portfolio/orders", json=order_data)
        order = response.get("order", response)

        # Log order details for debugging
        logger.info(f"Order response: status={order.get('status')}, "
                    f"filled={order.get('filled_count', 0)}/{order.get('count', 0)}, "
                    f"remaining={order.get('remaining_count', 'unknown')}")

        return order

    def get_orders(
        self,
        limit: int = 20,
        status: str = None
    ) -> list[dict]:
        """Get recent orders.

        Args:
            limit: Max orders to return
            status: Filter by status (resting, canceled, executed)

        Returns:
            List of order dictionaries
        """
        params = {"limit": limit}
        if status:
            params["status"] = status

        response = self._request("GET", "/portfolio/orders", json=params)
        return response.get("orders", [])

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a resting order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if canceled successfully, False otherwise
        """
        try:
            self._request("DELETE", f"/portfolio/orders/{order_id}")
            return True
        except KalshiError:
            return False

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

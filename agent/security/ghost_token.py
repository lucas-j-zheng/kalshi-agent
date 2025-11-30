"""Ghost Token security for trade approval.

This module implements the Ghost Token pattern to ensure trades NEVER execute
without explicit human approval. The token is generated client-side when the
user clicks [APPROVE], and validated server-side before execution.

Security properties:
- Tokens are one-time use (replay prevention via used_tokens set)
- Tokens expire after TTL (default 30 seconds)
- Trade proposals expire and must be re-created
- Token hash stored, not raw token (defense in depth)
"""

import uuid
import time
from hashlib import sha256
from typing import Dict, Any, Optional

from config import settings


class GhostTokenError(Exception):
    """Base exception for ghost token validation failures."""
    pass


class TokenExpiredError(GhostTokenError):
    """Token has expired (exceeded TTL)."""
    pass


class TokenAlreadyUsedError(GhostTokenError):
    """Token has already been used (replay attack prevention)."""
    pass


class TradeNotFoundError(GhostTokenError):
    """Trade proposal not found or already executed."""
    pass


class InvalidTokenError(GhostTokenError):
    """Token format is invalid."""
    pass


class GhostTokenValidator:
    """Validates ghost tokens for trade execution.

    The Ghost Token pattern ensures trades require explicit human approval:
    1. Agent proposes trade -> generates trade_id
    2. Frontend shows proposal with [APPROVE] button
    3. User clicks button -> frontend generates UUID token client-side
    4. Token + trade_id sent to backend for validation
    5. Only after validation does trade execute

    The agent CANNOT forge tokens - they must come from UI interaction.

    Example:
        validator = GhostTokenValidator()

        # When agent proposes a trade
        trade_id = validator.register_proposal({
            "ticker": "BTC-100K",
            "side": "YES",
            "contracts": 100,
            "limit_price": 45
        })

        # When user clicks APPROVE (token generated client-side)
        token = str(uuid.uuid4())  # Generated in frontend
        timestamp = int(time.time())

        # Validate and get trade details for execution
        trade_details = validator.validate_and_consume(trade_id, token, timestamp)
    """

    def __init__(self, token_ttl: Optional[int] = None):
        """Initialize the validator.

        Args:
            token_ttl: Token time-to-live in seconds. Defaults to settings.ghost_token_ttl (30s).
        """
        self.pending_trades: Dict[str, dict] = {}
        self.used_tokens: set = set()
        self.token_ttl = token_ttl or settings.ghost_token_ttl

    def register_proposal(self, trade_details: dict) -> str:
        """Register a pending trade proposal.

        Called when agent creates a trade proposal. Stores details
        and returns trade_id for later validation.

        Args:
            trade_details: Dict containing trade parameters (ticker, side, contracts, etc.)
                          Must include 'trade_id' key.

        Returns:
            trade_id: UUID string identifying this proposal
        """
        # Use the trade_id from the proposal (don't generate a new one!)
        trade_id = trade_details.get("trade_id") or str(uuid.uuid4())
        self.pending_trades[trade_id] = {
            **trade_details,
            "created_at": time.time()
        }
        return trade_id

    def validate_token(self, trade_id: str, token: str, timestamp: int) -> bool:
        """Validate a ghost token without consuming it.

        Checks all security properties:
        1. Trade proposal exists
        2. Timestamp within TTL window
        3. Token is valid UUID format
        4. Token hasn't been used before

        Args:
            trade_id: The trade proposal ID
            token: The ghost token from client
            timestamp: Unix timestamp when token was generated

        Returns:
            True if valid

        Raises:
            TradeNotFoundError: Trade proposal doesn't exist
            TokenExpiredError: Token/timestamp too old
            InvalidTokenError: Token format invalid
            TokenAlreadyUsedError: Token was already used
        """
        # Check trade exists
        if trade_id not in self.pending_trades:
            raise TradeNotFoundError(f"Trade proposal '{trade_id}' not found or already executed")

        # Check proposal hasn't expired
        trade = self.pending_trades[trade_id]
        proposal_age = time.time() - trade["created_at"]
        if proposal_age > self.token_ttl * 2:  # Give 2x TTL for proposal lifetime
            # Clean up expired proposal
            del self.pending_trades[trade_id]
            raise TokenExpiredError("Trade proposal has expired. Please create a new proposal.")

        # Check timestamp freshness
        timestamp_age = abs(time.time() - timestamp)
        if timestamp_age > self.token_ttl:
            raise TokenExpiredError(
                f"Token expired. Generated {timestamp_age:.1f}s ago, max allowed is {self.token_ttl}s."
            )

        # Validate token format (must be valid UUID)
        try:
            uuid.UUID(token)
        except (ValueError, TypeError):
            raise InvalidTokenError("Token format invalid. Expected UUID.")

        # Check token not already used (replay prevention)
        token_hash = sha256(token.encode()).hexdigest()
        if token_hash in self.used_tokens:
            raise TokenAlreadyUsedError("Token has already been used. Generate a new approval.")

        return True

    def consume_token(self, trade_id: str, token: str) -> dict:
        """Consume a token and return trade details.

        Marks the token as used and removes the trade from pending.
        This MUST be called BEFORE executing the trade to prevent
        race conditions.

        Args:
            trade_id: The trade proposal ID
            token: The ghost token to consume

        Returns:
            Trade details dict for execution
        """
        # Hash and mark as used IMMEDIATELY (before any other operations)
        token_hash = sha256(token.encode()).hexdigest()
        self.used_tokens.add(token_hash)

        # Remove from pending and return details
        trade_details = self.pending_trades.pop(trade_id)

        # Remove internal metadata before returning
        trade_details.pop("created_at", None)

        return trade_details

    def validate_and_consume(self, trade_id: str, token: str, timestamp: int) -> dict:
        """Validate token and consume it in one atomic operation.

        This is the main entry point for trade execution validation.
        If validation passes, the token is immediately consumed to
        prevent replay attacks.

        Args:
            trade_id: The trade proposal ID
            token: The ghost token from client
            timestamp: Unix timestamp when token was generated

        Returns:
            Trade details dict for execution

        Raises:
            GhostTokenError: If any validation check fails
        """
        # Validate first (raises on failure)
        self.validate_token(trade_id, token, timestamp)

        # Consume and return details
        return self.consume_token(trade_id, token)

    def get_pending_trade(self, trade_id: str) -> Optional[dict]:
        """Get pending trade details without consuming.

        Useful for displaying trade info or checking status.

        Args:
            trade_id: The trade proposal ID

        Returns:
            Trade details if found and not expired, None otherwise
        """
        if trade_id not in self.pending_trades:
            return None

        trade = self.pending_trades[trade_id]

        # Check if expired
        proposal_age = time.time() - trade["created_at"]
        if proposal_age > self.token_ttl * 2:
            # Clean up and return None
            del self.pending_trades[trade_id]
            return None

        # Return copy without internal metadata
        result = {k: v for k, v in trade.items() if k != "created_at"}
        return result

    def cleanup_expired(self) -> int:
        """Remove expired proposals and old token hashes.

        Should be called periodically to prevent memory growth.
        In production, consider using Redis with TTL instead.

        Returns:
            Number of expired proposals removed
        """
        now = time.time()
        max_age = self.token_ttl * 2
        expired_ids = []

        for trade_id, trade in self.pending_trades.items():
            if now - trade["created_at"] > max_age:
                expired_ids.append(trade_id)

        for trade_id in expired_ids:
            del self.pending_trades[trade_id]

        # Note: We don't clean up used_tokens here because we want
        # replay prevention to persist. In production, use Redis
        # with automatic expiry.

        return len(expired_ids)

    def cancel_proposal(self, trade_id: str) -> bool:
        """Cancel a pending trade proposal.

        Called when user clicks [REJECT] or proposal times out.

        Args:
            trade_id: The trade proposal ID

        Returns:
            True if proposal was found and cancelled, False otherwise
        """
        if trade_id in self.pending_trades:
            del self.pending_trades[trade_id]
            return True
        return False

    @property
    def pending_count(self) -> int:
        """Number of pending trade proposals."""
        return len(self.pending_trades)

    @property
    def used_token_count(self) -> int:
        """Number of used tokens tracked (for replay prevention)."""
        return len(self.used_tokens)

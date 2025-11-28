# Kalshi API Reference

Quick reference for the Kalshi Trade API used by the Kalshi Alpha Agent.

**Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
**Demo URL:** `https://demo-api.kalshi.co/trade-api/v2`
**Official Docs:** https://docs.kalshi.com/

---

## Table of Contents

1. [Authentication](#authentication)
2. [Key Concepts](#key-concepts)
3. [Public Endpoints](#public-endpoints-no-auth)
4. [Authenticated Endpoints](#authenticated-endpoints)
5. [Response Examples](#response-examples)
6. [Error Codes](#error-codes)

---

## Authentication

Kalshi uses **RSA-PSS signatures** for API authentication. Every authenticated request requires three headers:

| Header | Description |
|--------|-------------|
| `KALSHI-ACCESS-KEY` | Your API Key ID (UUID format) |
| `KALSHI-ACCESS-TIMESTAMP` | Current timestamp in **milliseconds** |
| `KALSHI-ACCESS-SIGNATURE` | RSA-PSS signature of `{timestamp}{method}{path}` |

### Signature Generation (Python)

```python
import base64
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

def load_private_key(file_path: str):
    with open(file_path, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )

def sign_request(private_key, timestamp_ms: str, method: str, path: str) -> str:
    """Sign: timestamp + method + path (without query params)"""
    # IMPORTANT: Strip query params from path before signing
    path_without_query = path.split('?')[0]
    message = f"{timestamp_ms}{method}{path_without_query}".encode('utf-8')

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

# Usage
private_key = load_private_key("keys/kalshi_private_key.pem")
timestamp_ms = str(int(datetime.now().timestamp() * 1000))
signature = sign_request(private_key, timestamp_ms, "GET", "/trade-api/v2/portfolio/balance")

headers = {
    "KALSHI-ACCESS-KEY": "your-api-key-id",
    "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    "KALSHI-ACCESS-SIGNATURE": signature,
}
```

### Getting API Keys

1. Log in to [kalshi.com/account/profile](https://kalshi.com/account/profile)
2. Navigate to "API Keys" section
3. Click "Create New API Key"
4. **Save the private key immediately** - it won't be shown again!

---

## Key Concepts

### Prices
- All prices are in **cents** (1-99), representing probability percentage
- `yes_price = 65` means 65% implied probability ($0.65 per contract)
- `no_price = 100 - yes_price` (always sum to ~100)
- Contracts pay $1.00 if correct, $0.00 if wrong

### Market Structure
- **Event**: Real-world occurrence (e.g., "2024 Election")
- **Market**: Specific binary outcome within an event (e.g., "Will Trump win?")
- **Series**: Template for recurring events (e.g., "Weekly Bitcoin Price")

### Order Types
- `limit`: Execute at specified price or better
- `market`: Execute immediately at best available price

### Sides
- `yes`: Betting the event WILL happen
- `no`: Betting the event WON'T happen
- **API uses lowercase**: `"yes"` / `"no"`

### Position Sign Convention
- **Positive** position = YES contracts owned
- **Negative** position = NO contracts owned

---

## Public Endpoints (No Auth)

### GET /exchange/status
Check if exchange is active and trading.

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/exchange/status"
```

**Response:**
```json
{
  "exchange_active": true,
  "trading_active": true,
  "exchange_estimated_resume_time": null
}
```

---

### GET /markets
List markets with optional filters.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Results per page (default: 100, max: 1000) |
| `cursor` | string | Pagination cursor |
| `status` | string | `unopened`, `open`, `closed`, `settled` |
| `event_ticker` | string | Filter by event |
| `tickers` | string | Comma-separated market tickers |

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/markets?limit=5&status=open"
```

**Response Fields:**
```json
{
  "markets": [{
    "ticker": "KXELONMARS-99",
    "event_ticker": "KXELONMARS-99",
    "title": "Will Elon Musk visit Mars before Aug 1, 2099?",
    "yes_sub_title": "Mars",
    "no_sub_title": "Mars",
    "status": "active",
    "yes_bid": 8,
    "yes_ask": 10,
    "no_bid": 90,
    "no_ask": 92,
    "last_price": 8,
    "volume": 19920,
    "volume_24h": 28,
    "open_interest": 13169,
    "close_time": "2099-08-01T04:59:00Z",
    "rules_primary": "If Elon Musk visits Mars..."
  }],
  "cursor": "..."
}
```

---

### GET /markets/{ticker}
Get a single market by ticker.

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/markets/KXELONMARS-99"
```

---

### GET /markets/{ticker}/orderbook
Get the order book for a specific market.

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/markets/KXELONMARS-99/orderbook"
```

**Response:**
```json
{
  "orderbook": {
    "yes": [[8, 126], [7, 720], [6, 200], [5, 700]],
    "yes_dollars": [["0.0800", 126], ["0.0700", 720]],
    "no": [[90, 533], [89, 3699], [88, 450]],
    "no_dollars": [["0.9000", 533], ["0.8900", 3699]]
  }
}
```
*Arrays are `[price_cents, quantity]` sorted by price level*

---

### GET /markets/trades
Get recent trades across all markets.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Results per page (default: 100) |
| `cursor` | string | Pagination cursor |
| `ticker` | string | Filter by market ticker |
| `min_ts` / `max_ts` | int | Unix timestamp filters |

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/markets/trades?limit=5"
```

**Response:**
```json
{
  "trades": [{
    "trade_id": "abc-123",
    "ticker": "KXNCAAFGAME-25NOV28SDSUUNM-SDSU",
    "count": 250,
    "yes_price": 53,
    "no_price": 47,
    "yes_price_dollars": "0.5300",
    "no_price_dollars": "0.4700",
    "taker_side": "yes",
    "created_time": "2025-11-28T05:54:56.569393Z"
  }],
  "cursor": "..."
}
```

---

### GET /series
List all series (templates for recurring events).

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Results per page (default: 100) |
| `cursor` | string | Pagination cursor |

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/series?limit=3"
```

**Response:**
```json
{
  "series": [{
    "ticker": "KXNFLEXACTWINSCLE",
    "title": "Pro football exact wins Cleveland",
    "category": "Sports",
    "frequency": "annual",
    "fee_type": "quadratic",
    "fee_multiplier": 1,
    "tags": ["Football"],
    "settlement_sources": [{"name": "ESPN", "url": "https://www.espn.com/"}],
    "contract_url": "https://kalshi-public-docs.s3.amazonaws.com/..."
  }],
  "cursor": "..."
}
```

---

### GET /series/{ticker}
Get a specific series by ticker.

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/series/KXELONMARS"
```

---

### GET /structured_targets
Get structured target entities (sports teams, players, etc.).

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Results per page |
| `cursor` | string | Pagination cursor |
| `type` | string | Filter by type (e.g., `ufc_competitor`, `soccer_team`) |

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/structured_targets?limit=5"
```

**Response:**
```json
{
  "structured_targets": [{
    "id": "uuid",
    "name": "Kevin Holland",
    "type": "ufc_competitor",
    "source_id": "sr:competitor:542073",
    "details": {
      "first_name": "Kevin",
      "last_name": "Holland",
      "country": "USA",
      "record": "0-0-0"
    }
  }, {
    "id": "uuid",
    "name": "Toulouse FC",
    "type": "soccer_team",
    "details": {
      "country": "FRA",
      "short_name": "Toulouse"
    }
  }]
}
```

---

### GET /events
List events (groups of related markets).

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `limit` | int | Results per page (default: 200, max: 200) |
| `status` | string | `open`, `closed`, `settled` |
| `with_nested_markets` | bool | Include full market objects in response |
| `series_ticker` | string | Filter by series |

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/events?limit=2&with_nested_markets=true"
```

**Response (with nested markets):**
```json
{
  "events": [{
    "event_ticker": "KXELONMARS-99",
    "series_ticker": "KXELONMARS",
    "title": "Will Elon Musk visit Mars in his lifetime?",
    "sub_title": "Before 2099",
    "category": "World",
    "mutually_exclusive": false,
    "collateral_return_type": "",
    "markets": [{
      "ticker": "KXELONMARS-99",
      "title": "Will Elon Musk visit Mars before Aug 1, 2099?",
      "status": "active",
      "yes_bid": 8,
      "yes_ask": 10,
      "no_bid": 90,
      "no_ask": 92,
      "last_price": 8,
      "volume": 19920,
      "open_interest": 13169,
      "liquidity": 5204120,
      "close_time": "2099-08-01T04:59:00Z",
      "can_close_early": true,
      "early_close_condition": "This market will close and expire early if the event occurs."
    }]
  }],
  "cursor": "..."
}
```

---

## Authenticated Endpoints

### GET /portfolio/balance
Get account balance and portfolio value.

```bash
curl "https://api.elections.kalshi.com/trade-api/v2/portfolio/balance" \
  -H "KALSHI-ACCESS-KEY: $KEY_ID" \
  -H "KALSHI-ACCESS-TIMESTAMP: $TIMESTAMP" \
  -H "KALSHI-ACCESS-SIGNATURE: $SIGNATURE"
```

**Response:**
```json
{
  "balance": 10000,
  "portfolio_value": 5000,
  "updated_ts": 1700000000
}
```
*All values in cents*

---

### GET /portfolio/positions
Get current positions.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `settlement_status` | string | `all`, `unsettled` (default), `settled` |
| `ticker` | string | Filter by market ticker |
| `event_ticker` | string | Filter by event ticker |
| `count_filter` | string | `position`, `total_traded` |

**Response:**
```json
{
  "market_positions": [{
    "ticker": "PRES-2024-DJT",
    "position": 100,
    "market_exposure": 5300,
    "market_exposure_dollars": "53.0000",
    "realized_pnl": 0,
    "total_traded": 5300,
    "fees_paid": 50
  }],
  "event_positions": [{
    "event_ticker": "PRES-2024",
    "event_exposure": 5300,
    "realized_pnl": 0
  }]
}
```

**Position Sign:**
- `position: 100` = 100 YES contracts
- `position: -50` = 50 NO contracts

---

### POST /portfolio/orders
Create a new order.

**Request Body:**
```json
{
  "ticker": "PRES-2024-DJT",
  "side": "yes",
  "action": "buy",
  "count": 100,
  "type": "limit",
  "yes_price": 53
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ticker` | string | Yes | Market ticker |
| `side` | string | Yes | `yes` or `no` |
| `action` | string | Yes | `buy` or `sell` |
| `count` | int | Yes | Number of contracts (≥1) |
| `type` | string | No | `limit` (default) or `market` |
| `yes_price` | int | For limit | Price in cents (1-99) |
| `no_price` | int | For limit | Alternative to yes_price |
| `time_in_force` | string | No | `good_till_canceled`, `fill_or_kill`, `immediate_or_cancel` |
| `client_order_id` | string | No | Your reference ID |

**Response:**
```json
{
  "order": {
    "order_id": "abc-123-def-456",
    "ticker": "PRES-2024-DJT",
    "side": "yes",
    "action": "buy",
    "type": "limit",
    "status": "resting",
    "yes_price": 53,
    "no_price": 47,
    "initial_count": 100,
    "remaining_count": 100,
    "fill_count": 0,
    "created_time": "2024-11-25T12:00:00Z"
  }
}
```

**Order Statuses:**
- `resting`: Order on book, waiting to fill
- `executed`: Fully filled
- `canceled`: Canceled by user or system

---

### DELETE /portfolio/orders/{order_id}
Cancel an existing order.

```bash
curl -X DELETE "https://api.elections.kalshi.com/trade-api/v2/portfolio/orders/abc-123" \
  -H "KALSHI-ACCESS-KEY: $KEY_ID" \
  -H "KALSHI-ACCESS-TIMESTAMP: $TIMESTAMP" \
  -H "KALSHI-ACCESS-SIGNATURE: $SIGNATURE"
```

**Response:** Returns the canceled order with `status: "canceled"`

---

### GET /portfolio/orders
List your orders.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `ticker` | string | Filter by market |
| `status` | string | `resting`, `canceled`, `executed` |

---

### GET /portfolio/fills
Get trade execution history.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `ticker` | string | Filter by market |
| `order_id` | string | Filter by order |
| `min_ts` / `max_ts` | int | Unix timestamp filters |

**Response:**
```json
{
  "fills": [{
    "fill_id": "fill-123",
    "order_id": "order-456",
    "ticker": "PRES-2024-DJT",
    "side": "yes",
    "action": "buy",
    "count": 50,
    "yes_price": 53,
    "no_price": 47,
    "is_taker": true,
    "created_time": "2024-11-25T12:00:00Z"
  }]
}
```

---

## Response Examples

### Successful Market Data (Tested Live)
```bash
$ curl "https://api.elections.kalshi.com/trade-api/v2/exchange/status"
{
  "exchange_active": true,
  "trading_active": true,
  "exchange_estimated_resume_time": null
}
```

### Market Object (Real Data)
```json
{
  "ticker": "KXELONMARS-99",
  "title": "Will Elon Musk visit Mars before Aug 1, 2099?",
  "status": "active",
  "yes_bid": 8,
  "yes_ask": 10,
  "yes_bid_dollars": "0.0800",
  "yes_ask_dollars": "0.1000",
  "no_bid": 90,
  "no_ask": 92,
  "last_price": 8,
  "volume": 19920,
  "open_interest": 13169,
  "close_time": "2099-08-01T04:59:00Z",
  "rules_primary": "If Elon Musk visits Mars before the earlier of his death or Aug 1, 2099, then the market resolves to Yes."
}
```

---

## Error Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 201 | Created (order submitted) |
| 400 | Bad request (invalid params) |
| 401 | Authentication error |
| 404 | Resource not found |
| 409 | Conflict (e.g., insufficient balance) |
| 429 | Rate limited |
| 500 | Server error |
| 503 | Service unavailable |

### Rate Limits
- Check [docs.kalshi.com/getting_started/rate_limits](https://docs.kalshi.com/getting_started/rate_limits) for current limits
- Use exponential backoff on 429 errors

---

## Important Notes for Our Agent

1. **Side Values**: API uses lowercase `"yes"` / `"no"` - matches our `Side` enum!

2. **Price Units**: Everything in cents (1-99), convert to dollars by dividing by 100

3. **Signing Path**: Strip query params before signing: `/trade-api/v2/orders` not `/trade-api/v2/orders?limit=5`

4. **Ghost Token Pattern**: Our agent NEVER auto-executes trades. Always:
   - Create proposal → Show user → Wait for approval → Execute

5. **Demo Environment**: Use `demo-api.kalshi.co` for testing without real money

---

## Quick Reference Card

### Public Endpoints (No Auth)

| Action | Method | Endpoint |
|--------|--------|----------|
| Exchange status | GET | `/exchange/status` |
| List markets | GET | `/markets` |
| Get market | GET | `/markets/{ticker}` |
| Get orderbook | GET | `/markets/{ticker}/orderbook` |
| Get trades | GET | `/markets/trades` |
| List events | GET | `/events` |
| Get event | GET | `/events/{ticker}` |
| List series | GET | `/series` |
| Get series | GET | `/series/{ticker}` |
| Structured targets | GET | `/structured_targets` |

### Authenticated Endpoints

| Action | Method | Endpoint |
|--------|--------|----------|
| Get balance | GET | `/portfolio/balance` |
| Get positions | GET | `/portfolio/positions` |
| Create order | POST | `/portfolio/orders` |
| Cancel order | DELETE | `/portfolio/orders/{id}` |
| List orders | GET | `/portfolio/orders` |
| Get fills | GET | `/portfolio/fills` |

---

## Endpoint Status Summary

**Tested & Working (Public):**
- ✅ `/exchange/status` - Returns trading status
- ✅ `/markets` - Returns market list with prices
- ✅ `/markets/{ticker}` - Returns single market details
- ✅ `/markets/{ticker}/orderbook` - Returns bid/ask depth
- ✅ `/markets/trades` - Returns recent trades with taker_side
- ✅ `/events` - Returns events (with optional nested markets)
- ✅ `/events/{ticker}` - Returns single event
- ✅ `/series` - Returns series with settlement sources
- ✅ `/series/{ticker}` - Returns single series
- ✅ `/structured_targets` - Returns sports entities

**Authenticated (Documented, requires API key):**
- 🔐 `/portfolio/balance` - Account balance
- 🔐 `/portfolio/positions` - Current positions
- 🔐 `/portfolio/orders` - Order management
- 🔐 `/portfolio/fills` - Trade history

---

*Last updated: 2025-11-27*
*Tested against production API*

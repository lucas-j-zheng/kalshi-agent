---
title: kalshi-alpha-agent
emoji: 📈
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.0.1
app_file: app.py
pinned: false
license: mit
tags:
  - mcp-in-action-track-xx
---

# Kalshi Alpha Agent

[![Demo](https://img.shields.io/badge/Demo-HuggingFace%20Spaces-yellow)](https://huggingface.co/spaces/lzheng35/kalshi-alpha-agent)

Convert natural language convictions into prediction market trades on [Kalshi](https://kalshi.com).

**Not an auto-trading bot** - every trade requires explicit human approval via the Ghost Token security pattern.

## What It Does

1. **Analyze** - Extract trading intent from natural language ("I think BTC hits 100k")
2. **Search** - Semantic search across 30k+ Kalshi markets using embeddings
3. **Propose** - Generate trade proposals with position sizing
4. **Approve** - Human clicks [APPROVE] to execute (Ghost Token validation)
5. **Execute** - Trade placed on Kalshi

## Setup

```bash
# 1. Environment
conda create -n kalshi python=3.11 && conda activate kalshi
pip install -r requirements.txt

# 2. API Keys - create .env file
KALSHI_API_KEY_ID=your_key           # from kalshi.com/account/api
KALSHI_PRIVATE_KEY_PATH=./keys/kalshi_private_key.pem
ANTHROPIC_API_KEY=your_key           # or GROQ_API_KEY (free)
OPENAI_API_KEY=your_key              # for embeddings

# 3. Kalshi RSA key
mkdir -p keys
# Download your private key from Kalshi and save to keys/kalshi_private_key.pem

# 4. Run
python main.py
```

## Usage

```bash
python main.py                  # API server (port 8000) + Gradio UI (port 8001)
python main.py --server-only    # API server only
python main.py --frontend-only  # Gradio UI only (server must be running)
python main.py --skip-index     # Skip market indexing on startup
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tools/analyze_conviction` | POST | Extract trading intent from statement |
| `/tools/search_markets` | POST | Semantic market search |
| `/tools/get_market_details` | POST | Live prices from Kalshi |
| `/tools/propose_trade` | POST | Create trade proposal |
| `/tools/execute_trade` | POST | Execute with ghost token |
| `/tools/cancel_proposal` | POST | Cancel pending proposal |
| `/tools/portfolio` | GET | Current positions |
| `/tools/balance` | GET | Account balance |
| `/health` | GET | Service health status |
| `/mcp/tools` | GET | MCP tool definitions |

## Architecture

```
kalshi-agent/
├── main.py                 # Entry point
├── config.py               # Settings from .env
├── models.py               # Pydantic models
├── services/
│   ├── kalshi_client.py    # Kalshi API (RSA-PSS auth)
│   └── llama_index_service.py  # ChromaDB vector search
├── agent/
│   ├── server.py           # FastAPI server
│   ├── tools/              # conviction, markets, trading
│   ├── prompts/            # LLM prompts
│   └── security/
│       └── ghost_token.py  # Trade approval validation
├── frontend/
│   └── app.py              # Gradio UI
└── app.py                  # HuggingFace Spaces entry
```

## Ghost Token Security

Prevents autonomous trading:

1. Agent calls `propose_trade` -> returns `trade_id`
2. User sees proposal, clicks [APPROVE]
3. Frontend generates one-time UUID token
4. `execute_trade` validates: UUID format, 30s TTL, not replayed
5. Only then does trade execute

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KALSHI_API_KEY_ID` | Yes | - | Kalshi API key |
| `KALSHI_PRIVATE_KEY_PATH` | Yes | `./keys/kalshi_private_key.pem` | RSA private key |
| `ANTHROPIC_API_KEY` | Yes* | - | Claude API key |
| `GROQ_API_KEY` | Yes* | - | Groq API key (free alternative) |
| `OPENAI_API_KEY` | Yes | - | For embeddings |
| `KALSHI_DEMO_MODE` | No | `true` | Use demo API |
| `MAX_TRADE_SIZE_USD` | No | `100` | Trade limit |
| `GHOST_TOKEN_TTL` | No | `30` | Approval window (seconds) |

*One of ANTHROPIC_API_KEY or GROQ_API_KEY required

## Development

```bash
conda activate kalshi
pytest                              # Run all tests
pytest tests/test_file.py -v        # Single file
pytest tests/test_file.py::test_name -v  # Single test
```

## Gradio UI

The Gradio frontend (`frontend/app.py`) provides:
- Chat interface for conviction input
- Trade proposal cards with approve/reject buttons
- Portfolio view
- Account balance display

[![Demo](https://img.shields.io/badge/Demo-HuggingFace%20Spaces-yellow)](https://huggingface.co/spaces/lzheng35/kalshi-alpha-agent)

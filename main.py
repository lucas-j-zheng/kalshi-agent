#!/usr/bin/env python3
"""Kalshi Alpha Agent - Entry Point.

Bootstraps all services and launches both the API server and Gradio frontend.

Usage:
    python main.py                 # Start both server and frontend
    python main.py --server-only   # Start only the API server
    python main.py --frontend-only # Start only the Gradio frontend
    python main.py --skip-index    # Skip market indexing on startup

Requirements:
    - Conda environment: kalshi (activate with `conda activate kalshi`)
    - Environment variables in .env file
    - Kalshi API key and private key configured
"""

import os
# Suppress tokenizers parallelism warning when forking
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import argparse
import asyncio
import logging
import sys
import threading
import time
from typing import Optional

import uvicorn

from config import settings


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("kalshi-agent")


def check_environment():
    """Verify environment is properly configured.

    Raises:
        SystemExit: If required configuration is missing
    """
    errors = []

    # Check required API keys
    if not settings.kalshi_api_key_id:
        errors.append("KALSHI_API_KEY_ID not set in .env")

    if not settings.anthropic_api_key and not settings.groq_api_key:
        errors.append("No LLM API key set. Add ANTHROPIC_API_KEY or GROQ_API_KEY (free) to .env")

    # Check private key file
    try:
        settings.get_private_key()
    except FileNotFoundError as e:
        errors.append(str(e))
    except ValueError as e:
        errors.append(str(e))

    if errors:
        logger.error("Configuration errors found:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error("\nPlease fix these issues and try again.")
        logger.error("See CLAUDE.md for setup instructions.")
        sys.exit(1)

    # Log configuration summary
    logger.info("Configuration loaded successfully")
    logger.info(f"  Kalshi API: {'DEMO' if settings.kalshi_demo_mode else 'PRODUCTION'}")
    llm_provider = "Anthropic" if settings.anthropic_api_key else "Groq (free)"
    logger.info(f"  LLM Provider: {llm_provider}")
    logger.info(f"  Max trade size: ${settings.max_trade_size_usd}")
    logger.info(f"  Ghost token TTL: {settings.ghost_token_ttl}s")


def run_api_server(host: str, port: int):
    """Run the FastAPI server.

    Args:
        host: Host to bind to
        port: Port to bind to
    """
    logger.info(f"Starting API server on http://{host}:{port}")

    uvicorn.run(
        "agent.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=False  # Reduce log noise
    )


def run_frontend(host: str, port: int):
    """Run the Gradio frontend.

    Args:
        host: Host to bind to
        port: Port to bind to
    """
    logger.info(f"Starting Gradio frontend on http://{host}:{port}")

    from frontend.app import create_app

    app = create_app()
    app.launch(
        server_name=host,
        server_port=port,
        share=False,
        show_error=True,
        quiet=True  # Reduce log noise
    )


def wait_for_server(host: str, port: int, timeout: int = 30) -> bool:
    """Wait for the API server to be ready.

    Args:
        host: Server host
        port: Server port
        timeout: Maximum seconds to wait

    Returns:
        True if server is ready, False if timeout
    """
    import httpx

    # Use 127.0.0.1 to avoid DNS resolution issues with localhost
    connect_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{connect_host}:{port}/health"
    start = time.time()
    last_status = None
    check_count = 0

    logger.info(f"Polling {url} for health status...")

    while time.time() - start < timeout:
        check_count += 1
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                status = data.get("status")
                if status != last_status:
                    logger.info(f"Health check #{check_count}: {status} (kalshi={data.get('kalshi_connected')}, index={data.get('index_ready')}, markets={data.get('markets_indexed')})")
                    last_status = status
                if status in ["healthy", "degraded"]:
                    return True
            else:
                if last_status != f"HTTP_{response.status_code}":
                    logger.warning(f"Health check #{check_count}: HTTP {response.status_code}")
                    last_status = f"HTTP_{response.status_code}"
        except httpx.ConnectError:
            # Server not yet listening - this is expected during startup
            if check_count % 20 == 1:  # Log every 10 seconds
                logger.info(f"Health check #{check_count}: waiting for server to start...")
        except Exception as e:
            if last_status != "error":
                logger.warning(f"Health check #{check_count} failed: {type(e).__name__}: {e}")
                last_status = "error"
        time.sleep(0.5)

    logger.error(f"Health check timed out after {check_count} attempts")
    return False


def main(
    server_only: bool = False,
    frontend_only: bool = False,
    skip_index: bool = False,
    host: Optional[str] = None,
    port: Optional[int] = None
):
    """Main entry point.

    Args:
        server_only: Only run the API server
        frontend_only: Only run the Gradio frontend
        skip_index: Skip market indexing on startup
        host: Override host from settings
        port: Override port from settings
    """
    host = host or settings.host
    port = port or settings.port
    frontend_port = port + 1

    # Check environment
    check_environment()

    logger.info("=" * 60)
    logger.info("  KALSHI ALPHA AGENT")
    logger.info("  Convert convictions into trades")
    logger.info("=" * 60)

    if skip_index:
        logger.info("Skipping market indexing (--skip-index)")
        # Set environment variable for server to skip indexing
        import os
        os.environ["SKIP_INDEX"] = "1"

    if server_only:
        # Just run the server
        logger.info("Running in server-only mode")
        run_api_server(host, port)

    elif frontend_only:
        # Just run the frontend (assumes server is already running)
        logger.info("Running in frontend-only mode")
        connect_host = "localhost" if host == "0.0.0.0" else host
        logger.info(f"Connecting to API at http://{connect_host}:{port}")

        if not wait_for_server(host, port, timeout=5):
            logger.warning("API server not responding - frontend may not work correctly")

        run_frontend(host, frontend_port)

    else:
        # Run both server and frontend
        logger.info("Starting both API server and frontend...")

        # Start server in background thread
        server_thread = threading.Thread(
            target=run_api_server,
            args=(host, port),
            daemon=True
        )
        server_thread.start()

        # Wait for server to be ready (indexing 30k+ markets can take 2-3 minutes)
        logger.info("Waiting for API server to initialize (this may take a few minutes on first run)...")
        if not wait_for_server(host, port, timeout=300):
            logger.error("API server failed to start within 5 minutes")
            logger.error("Try running with --server-only first, then --frontend-only")
            sys.exit(1)

        logger.info("API server is ready!")
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"  API Server:  http://{host}:{port}")
        logger.info(f"  Frontend:    http://{host}:{frontend_port}")
        logger.info(f"  Health:      http://{host}:{port}/health")
        logger.info("=" * 60)
        logger.info("")

        # Run frontend in main thread (blocking)
        try:
            run_frontend(host, frontend_port)
        except KeyboardInterrupt:
            logger.info("Shutting down...")


def cli():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Kalshi Alpha Agent - Convert convictions into trades",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                     # Start everything
    python main.py --server-only       # API server only
    python main.py --frontend-only     # Frontend only (server must be running)
    python main.py --skip-index        # Skip market indexing
    python main.py --port 9000         # Use custom port

Environment:
    Activate conda environment first: conda activate kalshi
    Configure .env file with API keys (see CLAUDE.md)
        """
    )

    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Only run the FastAPI server (no frontend)"
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="Only run the Gradio frontend (server must be running)"
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip market indexing on startup"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help=f"Host to bind to (default: {settings.host})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Base port for API server (default: {settings.port}, frontend uses port+1)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.server_only and args.frontend_only:
        parser.error("Cannot use both --server-only and --frontend-only")

    main(
        server_only=args.server_only,
        frontend_only=args.frontend_only,
        skip_index=args.skip_index,
        host=args.host,
        port=args.port
    )


if __name__ == "__main__":
    cli()

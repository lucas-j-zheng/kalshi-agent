#!/usr/bin/env python3
"""Refresh the market index with fresh data from Kalshi API."""

import shutil
from pathlib import Path

from config import settings
from services.llama_index_service import LlamaIndexService
from services.kalshi_client import KalshiClient


def main():
    # Delete old index
    if settings.chroma_path.exists():
        print(f"Deleting old index at {settings.chroma_path}...")
        shutil.rmtree(settings.chroma_path)

    # Initialize services
    print("Connecting to Kalshi...")
    client = KalshiClient()

    print("Initializing index...")
    service = LlamaIndexService()
    service.init_index()

    # Refresh with all markets
    print("Fetching and indexing markets (this may take a minute)...")
    count = service.refresh_index(client)

    print(f"Done! Indexed {count:,} markets with subtitles (yes_sub_title)")


if __name__ == "__main__":
    main()

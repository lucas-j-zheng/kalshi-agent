"""LlamaIndex service for semantic search over Kalshi markets.

Provides:
- Market indexing with embeddings (HuggingFace by default, free & local)
- Semantic search by natural language query
- Filtered search by category, status, date
- Persistent storage via ChromaDB
"""

from typing import Optional
from datetime import datetime, timezone

import chromadb
from chromadb.config import Settings as ChromaSettings

from llama_index.core import VectorStoreIndex, Document, StorageContext
from llama_index.core.settings import Settings as LlamaSettings
from llama_index.vector_stores.chroma import ChromaVectorStore

from config import settings
from models import MarketMatch


def _get_embed_model():
    """Get embedding model - uses HuggingFace (free) by default.

    Falls back to OpenAI if configured and HuggingFace fails.
    """
    # Try HuggingFace first (free, no API key needed)
    try:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        return HuggingFaceEmbedding(
            model_name="BAAI/bge-small-en-v1.5"  # Fast, good quality, ~130MB
        )
    except ImportError:
        pass

    # Fall back to OpenAI if available
    if settings.openai_api_key:
        from llama_index.embeddings.openai import OpenAIEmbedding
        return OpenAIEmbedding(
            model="text-embedding-3-small",
            api_key=settings.openai_api_key
        )

    raise RuntimeError(
        "No embedding model available. Install llama-index-embeddings-huggingface "
        "or set OPENAI_API_KEY in .env"
    )


class LlamaIndexService:
    """Semantic search service for Kalshi markets using LlamaIndex + ChromaDB.

    Provides:
    - Market indexing with embeddings
    - Semantic search by natural language query
    - Filtered search by category, status, date

    Example:
        service = LlamaIndexService()
        service.init_index()
        service.index_markets(markets)
        results = service.search_markets("bitcoin price", n_results=5)
    """

    COLLECTION_NAME = "kalshi_markets"

    def __init__(self):
        self.chroma_client: Optional[chromadb.PersistentClient] = None
        self.collection = None
        self.vector_store: Optional[ChromaVectorStore] = None
        self.index: Optional[VectorStoreIndex] = None
        self._initialized = False

    def init_index(self) -> int:
        """Initialize ChromaDB and LlamaIndex components.

        Creates persistent storage at settings.chroma_path.
        Configures OpenAI embeddings.

        Returns:
            Number of existing documents in the index
        """
        # Ensure chroma directory exists
        settings.chroma_path.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB with persistence
        self.chroma_client = chromadb.PersistentClient(
            path=str(settings.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        # Get or create collection
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "Kalshi prediction markets"}
        )

        # Create vector store from collection
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)

        # Configure LlamaIndex embeddings (HuggingFace by default, free & local)
        LlamaSettings.embed_model = _get_embed_model()

        # Check if we have existing data
        if self.collection.count() > 0:
            # Load existing index
            storage_context = StorageContext.from_defaults(
                vector_store=self.vector_store
            )
            self.index = VectorStoreIndex.from_vector_store(
                vector_store=self.vector_store,
                storage_context=storage_context
            )

        self._initialized = True
        return self.collection.count()

    def index_markets(self, markets: list[dict], clear_existing: bool = True) -> int:
        """Index markets for semantic search.

        Args:
            markets: List of market dicts from Kalshi API
            clear_existing: Whether to clear existing index first

        Returns:
            Number of markets indexed
        """
        if not self._initialized:
            self.init_index()

        if clear_existing and self.collection.count() > 0:
            # Delete all documents in collection
            # ChromaDB requires IDs to delete, so we get all IDs first
            existing = self.collection.get()
            if existing["ids"]:
                self.collection.delete(ids=existing["ids"])

        # Create documents from markets
        documents = []
        for market in markets:
            # Combine searchable text
            text = f"""
            {market.get('title', '')}
            {market.get('subtitle', '')}
            Category: {market.get('category', '')}
            {market.get('rules_primary', '')}
            """.strip()

            # Parse close_time safely
            close_time = market.get('close_time', '')
            if close_time:
                try:
                    close_dt = datetime.fromisoformat(
                        close_time.replace('Z', '+00:00')
                    )
                    close_timestamp = close_dt.timestamp()
                except (ValueError, TypeError):
                    close_timestamp = 0
            else:
                close_timestamp = 0

            # Clamp prices to valid range (1-99), default to 50 if missing/zero
            yes_price = market.get('yes_bid', 50) or 50
            no_price = market.get('no_bid', 50) or 50
            yes_price = max(1, min(99, yes_price))
            no_price = max(1, min(99, no_price))

            doc = Document(
                text=text,
                doc_id=market['ticker'],
                metadata={
                    'ticker': market['ticker'],
                    'title': market.get('title', ''),
                    'subtitle': market.get('subtitle', ''),
                    'category': market.get('category', ''),
                    'yes_price': yes_price,
                    'no_price': no_price,
                    'volume': market.get('volume', 0),
                    'close_time': close_time,
                    'close_timestamp': close_timestamp,
                    'status': market.get('status', 'open')
                }
            )
            documents.append(doc)

        if not documents:
            return 0

        # Build index from documents
        storage_context = StorageContext.from_defaults(
            vector_store=self.vector_store
        )
        self.index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True
        )

        return len(documents)

    def search_markets(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        only_active: bool = True
    ) -> list[MarketMatch]:
        """Search markets by semantic similarity.

        Args:
            query: Natural language search query
            n_results: Number of results to return
            category: Optional category filter
            only_active: Only return markets with future close_time

        Returns:
            List of MarketMatch objects sorted by relevance
        """
        if not self._initialized or self.index is None:
            return []

        # Build retriever - get extra for filtering
        retriever = self.index.as_retriever(
            similarity_top_k=n_results * 3
        )

        # Execute search
        nodes = retriever.retrieve(query)

        # Filter and convert results
        results = []
        now_timestamp = datetime.now(timezone.utc).timestamp()

        for node in nodes:
            meta = node.metadata

            # Filter by active status
            if only_active:
                close_ts = meta.get('close_timestamp', 0)
                if close_ts and close_ts < now_timestamp:
                    continue

            # Filter by category
            if category and meta.get('category', '').lower() != category.lower():
                continue

            # Parse close_time
            close_time_str = meta.get('close_time', '')
            try:
                close_time = datetime.fromisoformat(
                    close_time_str.replace('Z', '+00:00')
                )
            except (ValueError, TypeError):
                close_time = datetime.now(timezone.utc)

            # Clamp prices to valid range (1-99)
            yes_price = max(1, min(99, meta.get('yes_price', 50) or 50))
            no_price = max(1, min(99, meta.get('no_price', 50) or 50))

            results.append(MarketMatch(
                ticker=meta['ticker'],
                title=meta.get('title', ''),
                subtitle=meta.get('subtitle', ''),
                category=meta.get('category', ''),
                yes_price=yes_price,
                no_price=no_price,
                volume=meta.get('volume', 0),
                close_time=close_time,
                relevance_score=node.score if node.score else 0.0
            ))

            if len(results) >= n_results:
                break

        # Sort by relevance score descending
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        return results

    def get_market_by_ticker(self, ticker: str) -> Optional[MarketMatch]:
        """Get a market from index by exact ticker match.

        Args:
            ticker: Market ticker to find

        Returns:
            MarketMatch if found, None otherwise
        """
        if not self._initialized:
            return None

        # Query ChromaDB directly for exact match
        results = self.collection.get(
            ids=[ticker],
            include=["metadatas"]
        )

        if not results['ids']:
            return None

        meta = results['metadatas'][0]

        # Parse close_time
        close_time_str = meta.get('close_time', '')
        try:
            close_time = datetime.fromisoformat(
                close_time_str.replace('Z', '+00:00')
            )
        except (ValueError, TypeError):
            close_time = datetime.now(timezone.utc)

        # Clamp prices to valid range (1-99)
        yes_price = max(1, min(99, meta.get('yes_price', 50) or 50))
        no_price = max(1, min(99, meta.get('no_price', 50) or 50))

        return MarketMatch(
            ticker=meta['ticker'],
            title=meta.get('title', ''),
            subtitle=meta.get('subtitle', ''),
            category=meta.get('category', ''),
            yes_price=yes_price,
            no_price=no_price,
            volume=meta.get('volume', 0),
            close_time=close_time,
            relevance_score=1.0  # Exact match
        )

    def refresh_index(self, kalshi_client) -> int:
        """Refresh index with current markets from Kalshi.

        Args:
            kalshi_client: KalshiClient instance

        Returns:
            Number of markets indexed
        """
        markets = kalshi_client.get_all_markets(status="open")
        count = self.index_markets(markets, clear_existing=True)
        return count

    def get_stats(self) -> dict:
        """Get index statistics.

        Returns:
            Dict with count, categories, initialization status
        """
        if not self._initialized:
            return {"initialized": False, "count": 0}

        # Get all metadata to compute stats
        all_data = self.collection.get(include=["metadatas"])

        categories = {}
        for meta in all_data.get('metadatas', []):
            cat = meta.get('category', 'Unknown')
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "initialized": True,
            "count": self.collection.count(),
            "categories": categories,
            "chroma_path": str(settings.chroma_path)
        }

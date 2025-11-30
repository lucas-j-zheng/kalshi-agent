from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra env vars not defined in model
    )

    # Kalshi API Configuration
    kalshi_api_key_id: str = ""  # Optional in demo mode
    kalshi_private_key_path: Optional[Path] = Path("./keys/kalshi_private_key.pem")
    kalshi_private_key: str = ""  # Private key content (PEM) - alternative to file path
    kalshi_demo_mode: bool = True  # Use demo API (fake money) by default

    @property
    def kalshi_api_host(self) -> str:
        """Get Kalshi API host based on demo_mode setting."""
        if self.kalshi_demo_mode:
            return "https://demo-api.kalshi.co/trade-api/v2"
        return "https://api.elections.kalshi.com/trade-api/v2"

    # LLM Configuration
    anthropic_api_key: str = ""  # Optional - uses Groq if not set
    openai_api_key: str = ""  # Optional - only needed if not using HuggingFace embeddings
    groq_api_key: str = ""  # Free alternative - get key at https://console.groq.com

    # Optional Services (for future features)
    tavily_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"  # "George" voice

    # Trading Settings
    max_trade_size_usd: int = 100  # Maximum single trade size

    # Security Settings
    ghost_token_ttl: int = 30  # Seconds before approval token expires

    # Storage Paths
    database_path: Path = Path("./data/markets.db")
    chroma_path: Path = Path("./data/chroma")

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    def get_private_key(self) -> bytes:
        """Load RSA private key for Kalshi API authentication.

        Checks env var KALSHI_PRIVATE_KEY first, then falls back to file.

        Returns:
            bytes: The raw private key bytes

        Raises:
            FileNotFoundError: If key file doesn't exist and no env var set
            ValueError: If key is empty or invalid
        """
        # First, try env var (for HF Spaces / cloud deployment)
        if self.kalshi_private_key:
            key_bytes = self.kalshi_private_key.encode("utf-8")
            # Handle escaped newlines from env var
            key_bytes = key_bytes.replace(b"\\n", b"\n")

            if b"PRIVATE KEY" not in key_bytes:
                raise ValueError(
                    "Invalid KALSHI_PRIVATE_KEY format.\n"
                    "Expected PEM format with 'PRIVATE KEY' header"
                )
            return key_bytes

        # Fall back to file path
        key_path = self.kalshi_private_key_path

        if not key_path or not key_path.exists():
            raise FileNotFoundError(
                f"Kalshi private key not found at: {key_path}\n"
                f"Set KALSHI_PRIVATE_KEY env var or place key file.\n"
                f"Generate one at: https://kalshi.com/account/api"
            )

        key_bytes = key_path.read_bytes()

        if not key_bytes:
            raise ValueError(f"Private key file is empty: {key_path}")

        if b"PRIVATE KEY" not in key_bytes:
            raise ValueError(
                f"Invalid private key format in: {key_path}\n"
                f"Expected PEM format with 'PRIVATE KEY' header"
            )

        return key_bytes


# Singleton instance - import this in other modules
# Will fail fast if required env vars are missing
settings = Settings()

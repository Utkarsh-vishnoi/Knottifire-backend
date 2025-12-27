"""
Application configuration loaded from environment variables.
"""

import os
from pathlib import Path


class Config:
    """Global application configuration."""

    # API Authentication
    API_KEY: str = os.getenv("API_KEY", "your-webhook-api-key")
    ACK_SECRET: str = os.getenv("ACK_SECRET", "dev-ack-secret-change-in-production")

    # Firebase Configuration
    FCM_CREDENTIALS_PATH: str = os.getenv(
        "FCM_CREDENTIALS_PATH",
        str(Path(__file__).parent.parent.parent / "firebase-credentials.json")
    )
    FCM_DEVICE_TOKEN: str = os.getenv("FCM_DEVICE_TOKEN", "")

    # Database
    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH",
        str(Path(__file__).parent.parent.parent / "queue.db")
    )

    # Queue Settings
    WORKER_POLL_INTERVAL: int = int(os.getenv("WORKER_POLL_INTERVAL", "10"))  # seconds

    # Retry Configuration (by priority)
    RETRY_CONFIG = {
        "critical": {
            "base_delay": 30,  # seconds
            "max_retries": 100,
            "ttl": 7 * 24 * 3600,  # 7 days
        },
        "important": {
            "base_delay": 120,  # 2 minutes
            "max_retries": 50,
            "ttl": 3 * 24 * 3600,  # 3 days
        },
        "info": {
            "base_delay": 600,  # 10 minutes
            "max_retries": 20,
            "ttl": 24 * 3600,  # 1 day
        },
        "silent": {
            "base_delay": 1800,  # 30 minutes
            "max_retries": 5,
            "ttl": 6 * 3600,  # 6 hours
        },
    }

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))


config = Config()

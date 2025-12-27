"""
Queue interface definition.
Allows swapping SQLite implementation with Redis/PostgreSQL in future.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime


class QueueMessage:
    """Represents a message in the queue."""

    def __init__(
        self,
        id: int,
        message_id: str,
        priority: str,
        payload: str,  # JSON string
        fcm_token: str,
        created_at: float,
        ttl_seconds: int,
        retry_count: int,
        next_retry_at: float,
        last_error: Optional[str] = None,
        raw_payload: Optional[str] = None,  # Original webhook JSON for debugging
    ):
        self.id = id
        self.message_id = message_id
        self.priority = priority
        self.payload = payload
        self.fcm_token = fcm_token
        self.created_at = created_at
        self.ttl_seconds = ttl_seconds
        self.retry_count = retry_count
        self.next_retry_at = next_retry_at
        self.last_error = last_error
        self.raw_payload = raw_payload

    @property
    def is_expired(self) -> bool:
        """Check if message has exceeded TTL."""
        import time
        return time.time() > (self.created_at + self.ttl_seconds)


class NotificationQueue(ABC):
    """Abstract queue interface."""

    @abstractmethod
    def enqueue(
        self,
        message_id: str,
        priority: str,
        payload: str,
        fcm_token: str,
        ttl_seconds: int,
        raw_payload: Optional[str] = None,
    ) -> bool:
        """
        Add message to queue.
        Returns True if added, False if duplicate (message_id exists).

        Args:
            message_id: Unique identifier for deduplication
            priority: Notification priority level
            payload: Canonical notification payload (JSON string)
            fcm_token: Device FCM token
            ttl_seconds: Time to live in seconds
            raw_payload: Original webhook payload for debugging (optional)
        """
        pass

    @abstractmethod
    def get_pending_messages(self, limit: int = 100) -> List[QueueMessage]:
        """
        Get messages ready for retry (next_retry_at <= now).
        Ordered by priority (critical first), then next_retry_at (oldest first).
        """
        pass

    @abstractmethod
    def update_retry(
        self,
        message_id: str,
        retry_count: int,
        next_retry_at: float,
        last_error: Optional[str] = None,
    ) -> None:
        """Update retry count and next retry time after failed send."""
        pass

    @abstractmethod
    def acknowledge(self, message_id: str) -> bool:
        """
        Remove message from queue (delivery confirmed).
        Returns True if removed, False if not found.
        """
        pass

    @abstractmethod
    def move_to_dead_letter(self, message_id: str, reason: str) -> None:
        """Move message to dead letter queue (expired or max retries)."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics for health endpoint."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close database connections."""
        pass

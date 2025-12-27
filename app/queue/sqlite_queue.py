"""
SQLite-based persistent queue implementation.
Thread-safe for single-writer (worker) + multiple-readers (webhook) scenario.
"""

import sqlite3
import time
from typing import List, Optional, Dict, Any
from pathlib import Path
from app.queue.interface import NotificationQueue, QueueMessage
from app.core.logging import get_logger


logger = get_logger("queue.sqlite")


class SQLiteQueue(NotificationQueue):
    """SQLite-backed notification queue with dead letter support."""

    PRIORITY_ORDER = {"critical": 0, "important": 1, "info": 2, "silent": 3}

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_database()
        logger.info(f"SQLite queue initialized at {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")  # Write-ahead logging for concurrency
        conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety and performance
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_database(self) -> None:
        """Create database schema if not exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE NOT NULL,
                    priority TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    fcm_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ttl_seconds INTEGER NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    next_retry_at REAL NOT NULL,
                    last_error TEXT,
                    raw_payload TEXT
                )
            """)

            # Add raw_payload column to existing tables (migration)
            try:
                conn.execute("ALTER TABLE notification_queue ADD COLUMN raw_payload TEXT")
                logger.info("Added raw_payload column to notification_queue table")
            except sqlite3.OperationalError:
                # Column already exists
                pass

            # Index for efficient polling by worker
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_next_retry
                ON notification_queue(next_retry_at, priority)
            """)

            # Dead letter table for failed messages
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letter (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    failed_at REAL NOT NULL,
                    retry_count INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    last_error TEXT,
                    raw_payload TEXT
                )
            """)

            # Add raw_payload column to existing dead_letter tables (migration)
            try:
                conn.execute("ALTER TABLE dead_letter ADD COLUMN raw_payload TEXT")
                logger.info("Added raw_payload column to dead_letter table")
            except sqlite3.OperationalError:
                # Column already exists
                pass

            conn.commit()
            logger.info("Database schema initialized")
        finally:
            conn.close()

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
        Returns True if added, False if duplicate.
        """
        conn = self._get_connection()
        try:
            now = time.time()
            conn.execute("""
                INSERT INTO notification_queue
                (message_id, priority, payload, fcm_token, created_at, ttl_seconds, next_retry_at, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, priority, payload, fcm_token, now, ttl_seconds, now, raw_payload))
            conn.commit()
            logger.info(f"Enqueued message {message_id} with priority {priority}")
            return True
        except sqlite3.IntegrityError:
            # Duplicate message_id (UNIQUE constraint)
            logger.info(f"Duplicate message {message_id}, skipping enqueue")
            return False
        finally:
            conn.close()

    def get_pending_messages(self, limit: int = 100) -> List[QueueMessage]:
        """
        Get messages ready for retry.
        Ordered by priority, then next_retry_at.
        """
        conn = self._get_connection()
        try:
            now = time.time()
            rows = conn.execute("""
                SELECT * FROM notification_queue
                WHERE next_retry_at <= ?
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'important' THEN 1
                        WHEN 'info' THEN 2
                        WHEN 'silent' THEN 3
                    END,
                    next_retry_at ASC
                LIMIT ?
            """, (now, limit)).fetchall()

            messages = []
            for row in rows:
                msg = QueueMessage(
                    id=row["id"],
                    message_id=row["message_id"],
                    priority=row["priority"],
                    payload=row["payload"],
                    fcm_token=row["fcm_token"],
                    created_at=row["created_at"],
                    ttl_seconds=row["ttl_seconds"],
                    retry_count=row["retry_count"],
                    next_retry_at=row["next_retry_at"],
                    last_error=row["last_error"],
                    raw_payload=row["raw_payload"],
                )
                messages.append(msg)

            return messages
        finally:
            conn.close()

    def update_retry(
        self,
        message_id: str,
        retry_count: int,
        next_retry_at: float,
        last_error: Optional[str] = None,
    ) -> None:
        """Update retry count and next retry time after failed send."""
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE notification_queue
                SET retry_count = ?, next_retry_at = ?, last_error = ?
                WHERE message_id = ?
            """, (retry_count, next_retry_at, last_error, message_id))
            conn.commit()
            logger.info(f"Updated retry for {message_id}: count={retry_count}, next_retry={next_retry_at}")
        finally:
            conn.close()

    def acknowledge(self, message_id: str) -> bool:
        """
        Remove message from queue (delivery confirmed).
        Returns True if removed, False if not found.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                DELETE FROM notification_queue WHERE message_id = ?
            """, (message_id,))
            conn.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Acknowledged and removed {message_id} from queue")
            else:
                logger.warning(f"ACK for {message_id} but message not in queue (already removed or expired)")

            return deleted
        finally:
            conn.close()

    def move_to_dead_letter(self, message_id: str, reason: str) -> None:
        """Move message to dead letter queue."""
        conn = self._get_connection()
        try:
            # Get message from queue
            row = conn.execute("""
                SELECT * FROM notification_queue WHERE message_id = ?
            """, (message_id,)).fetchone()

            if not row:
                logger.warning(f"Cannot move {message_id} to dead letter: not found in queue")
                return

            # Insert into dead letter
            now = time.time()
            conn.execute("""
                INSERT INTO dead_letter
                (message_id, priority, payload, created_at, failed_at, retry_count, reason, last_error, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["message_id"],
                row["priority"],
                row["payload"],
                row["created_at"],
                now,
                row["retry_count"],
                reason,
                row["last_error"],
                row["raw_payload"],
            ))

            # Delete from queue
            conn.execute("DELETE FROM notification_queue WHERE message_id = ?", (message_id,))
            conn.commit()

            logger.warning(f"Moved {message_id} to dead letter: {reason}")
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics for health endpoint."""
        conn = self._get_connection()
        try:
            # Total count by priority
            rows = conn.execute("""
                SELECT priority, COUNT(*) as count
                FROM notification_queue
                GROUP BY priority
            """).fetchall()

            by_priority = {row["priority"]: row["count"] for row in rows}
            total = sum(by_priority.values())

            # Oldest message age
            oldest = conn.execute("""
                SELECT MIN(created_at) as oldest_created_at
                FROM notification_queue
            """).fetchone()

            oldest_age = None
            if oldest["oldest_created_at"]:
                oldest_age = time.time() - oldest["oldest_created_at"]

            # Dead letter count
            dead_letter_count = conn.execute("""
                SELECT COUNT(*) as count FROM dead_letter
            """).fetchone()["count"]

            return {
                "total": total,
                "by_priority": {
                    "critical": by_priority.get("critical", 0),
                    "important": by_priority.get("important", 0),
                    "info": by_priority.get("info", 0),
                    "silent": by_priority.get("silent", 0),
                },
                "oldest_message_age_seconds": oldest_age,
                "dead_letter_count": dead_letter_count,
            }
        finally:
            conn.close()

    def close(self) -> None:
        """Close database connections (SQLite connections are per-call, no persistent connection)."""
        logger.info("SQLite queue closed")

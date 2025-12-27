"""
Background worker that consumes queue and sends to FCM.
Runs as async task in main.py.
"""

import asyncio
import time
import json
from typing import Optional
from firebase_admin import messaging
from app.queue.interface import NotificationQueue, QueueMessage
from app.core.config import config
from app.core.logging import get_logger


logger = get_logger("worker")


class NotificationWorker:
    """Background worker for FCM delivery."""

    def __init__(self, queue: NotificationQueue):
        self.queue = queue
        self.running = False
        self.last_run: Optional[float] = None

    async def start(self) -> None:
        """Start worker loop."""
        self.running = True
        logger.info("Notification worker started")

        while self.running:
            try:
                await self._process_batch()
                self.last_run = time.time()
                await asyncio.sleep(config.WORKER_POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Brief pause on error

    def stop(self) -> None:
        """Stop worker loop."""
        self.running = False
        logger.info("Notification worker stopped")

    async def _process_batch(self) -> None:
        """Process a batch of pending messages."""
        messages = self.queue.get_pending_messages(limit=100)

        if not messages:
            return

        logger.info(f"Processing {len(messages)} pending messages")

        for msg in messages:
            await self._process_message(msg)

    async def _process_message(self, msg: QueueMessage) -> None:
        """
        Process a single message.
        Checks TTL, sends to FCM, updates retry state.
        """
        # Check if expired
        if msg.is_expired:
            logger.warning(f"Message {msg.message_id} expired (TTL exceeded)")
            self.queue.move_to_dead_letter(msg.message_id, "TTL expired")
            return

        # Get retry config for this priority
        retry_config = config.RETRY_CONFIG.get(msg.priority, config.RETRY_CONFIG["info"])

        # Check if max retries exceeded
        if msg.retry_count >= retry_config["max_retries"]:
            logger.warning(f"Message {msg.message_id} exceeded max retries ({msg.retry_count})")
            self.queue.move_to_dead_letter(msg.message_id, f"Max retries ({retry_config['max_retries']}) exceeded")
            return

        # Attempt FCM send
        success, error = await self._send_to_fcm(msg)

        if success:
            logger.info(f"Successfully sent {msg.message_id} to FCM (attempt {msg.retry_count + 1})")
            # Message stays in queue until ACK received from Android
        else:
            # Update retry state with exponential backoff
            new_retry_count = msg.retry_count + 1
            base_delay = retry_config["base_delay"]
            backoff_delay = base_delay * (2 ** min(msg.retry_count, 8))  # Cap at 2^8 multiplier
            next_retry = time.time() + backoff_delay

            self.queue.update_retry(
                message_id=msg.message_id,
                retry_count=new_retry_count,
                next_retry_at=next_retry,
                last_error=error,
            )

            logger.warning(
                f"Failed to send {msg.message_id} (attempt {new_retry_count}), "
                f"retrying in {backoff_delay}s: {error}"
            )

    async def _send_to_fcm(self, msg: QueueMessage) -> tuple[bool, Optional[str]]:
        """
        Send message to FCM.
        Returns (success, error_message).
        """
        try:
            # Parse payload
            payload_data = json.loads(msg.payload)

            # Build FCM message
            # Use data payload (not notification) to ensure onMessageReceived is called
            # even when app is in foreground/background
            fcm_message = messaging.Message(
                data={
                    "version": payload_data["version"],
                    "message_id": payload_data["message_id"],
                    "title": payload_data["title"],
                    "body": payload_data["body"],
                    "priority": payload_data["priority"],
                    "tags": json.dumps(payload_data["tags"]),
                    "source": payload_data["source"],
                    "timestamp": payload_data["timestamp"],
                },
                token=msg.fcm_token,
                android=messaging.AndroidConfig(
                    priority="high",  # Bypass Doze mode
                    ttl=msg.ttl_seconds,
                ),
            )

            # Send to FCM (this is sync, but fast)
            response = await asyncio.to_thread(messaging.send, fcm_message)
            logger.info(f"FCM send response for {msg.message_id}: {response}")

            return True, None

        except messaging.UnregisteredError:
            # FCM token invalid/expired
            error = "FCM token unregistered or expired"
            logger.error(f"FCM token error for {msg.message_id}: {error}")
            return False, error

        except Exception as e:
            error = str(e)
            logger.error(f"FCM send error for {msg.message_id}: {error}", exc_info=True)
            return False, error

    def is_alive(self) -> bool:
        """Check if worker has run recently (last 60 seconds)."""
        if not self.last_run:
            return False
        return (time.time() - self.last_run) < 60


# Global worker instance (initialized in main.py)
_worker_instance: Optional[NotificationWorker] = None


def get_worker() -> Optional[NotificationWorker]:
    """Get global worker instance."""
    return _worker_instance


def set_worker(worker: NotificationWorker) -> None:
    """Set global worker instance."""
    global _worker_instance
    _worker_instance = worker

"""
ACK API endpoint for delivery confirmation from Android.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.models.notification import AckRequest, AckResponse
from app.core.auth import verify_ack_token
from app.core.logging import get_logger
from app.queue.sqlite_queue import SQLiteQueue


logger = get_logger("api.ack")
router = APIRouter()

# Queue instance (shared with webhook.py)
_queue_instance: SQLiteQueue = None


def get_queue() -> SQLiteQueue:
    """Dependency to get queue instance."""
    return _queue_instance


def set_queue(queue: SQLiteQueue) -> None:
    """Set queue instance (called from main.py)."""
    global _queue_instance
    _queue_instance = queue


@router.post("/ack", response_model=AckResponse)
async def acknowledge_delivery(
    ack: AckRequest,
    _: str = Depends(verify_ack_token),
    queue: SQLiteQueue = Depends(get_queue),
) -> AckResponse:
    """
    Receive acknowledgment from Android that notification was delivered.

    - Removes message from queue
    - Returns 404 if message not found (already ACK'd or expired)
    - Idempotent (safe to retry)
    """
    logger.info(
        f"Received ACK for message {ack.message_id} at device time {ack.device_timestamp}",
        extra={"message_id": ack.message_id}
    )

    # Remove from queue
    removed = queue.acknowledge(ack.message_id)

    if not removed:
        logger.warning(f"ACK for {ack.message_id} but message not in queue")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found in queue",
        )

    return AckResponse(
        status="acknowledged",
        message_id=ack.message_id,
    )

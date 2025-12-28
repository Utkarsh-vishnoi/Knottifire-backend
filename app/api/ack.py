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

    Multi-device strategy:
    - Records ACK for this specific device
    - Removes message from queue ONLY when ALL active devices have acknowledged
    - Returns 404 if device not registered
    - Idempotent (safe to retry)
    """
    logger.info(
        f"Received ACK for message {ack.message_id} from device {ack.device_id} at {ack.device_timestamp}",
        extra={"message_id": ack.message_id, "device_id": ack.device_id}
    )

    # Verify device is registered
    device = queue.get_device(ack.device_id)
    if not device:
        logger.warning(f"ACK from unregistered device: {ack.device_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not registered. Please register device first.",
        )

    # Record ACK for this device
    ack_recorded = queue.insert_ack(ack.message_id, ack.device_id, ack.device_timestamp)
    if not ack_recorded:
        logger.error(f"Failed to record ACK for {ack.message_id} from {ack.device_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record acknowledgment",
        )

    # Check if ALL active devices have acknowledged
    active_device_count = queue.count_active_devices()
    ack_count = queue.count_acks_for_message(ack.message_id)

    logger.info(
        f"Message {ack.message_id}: {ack_count}/{active_device_count} devices acknowledged",
        extra={"message_id": ack.message_id, "ack_count": ack_count, "total_devices": active_device_count}
    )

    if ack_count >= active_device_count:
        # All devices have acknowledged - remove from queue
        removed = queue.acknowledge(ack.message_id)
        if removed:
            logger.info(
                f"All devices acknowledged - removed {ack.message_id} from queue",
                extra={"message_id": ack.message_id}
            )
        else:
            logger.warning(
                f"All devices ACK'd but message {ack.message_id} not in queue (already removed or expired)",
                extra={"message_id": ack.message_id}
            )

    return AckResponse(
        status="acknowledged",
        message_id=ack.message_id,
    )

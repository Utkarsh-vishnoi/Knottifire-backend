"""
Device Management API endpoints for multi-device FCM registration.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from app.models.notification import DeviceRegistrationRequest, DeviceRegistrationResponse
from app.core.auth import verify_ack_token
from app.core.logging import get_logger
from app.queue.sqlite_queue import SQLiteQueue


logger = get_logger("api.devices")
router = APIRouter(prefix="/devices", tags=["devices"])

# Queue instance (shared with other modules)
_queue_instance: SQLiteQueue = None


def get_queue() -> SQLiteQueue:
    """Dependency to get queue instance."""
    return _queue_instance


def set_queue(queue: SQLiteQueue) -> None:
    """Set queue instance (called from main.py)."""
    global _queue_instance
    _queue_instance = queue


@router.post("/register", response_model=DeviceRegistrationResponse)
async def register_device(
    request: DeviceRegistrationRequest,
    _: str = Depends(verify_ack_token),
    queue: SQLiteQueue = Depends(get_queue),
) -> DeviceRegistrationResponse:
    """
    Register or update a device with its FCM token.

    - Creates new device entry if device_id doesn't exist
    - Updates FCM token and metadata if device_id already exists
    - Marks device as active and updates last_seen timestamp
    - Requires ACK_SECRET authentication (Bearer token)
    """
    logger.info(
        f"Device registration request: {request.device_id} ({request.device_name})",
        extra={"device_id": request.device_id}
    )

    success = queue.register_device(
        device_id=request.device_id,
        fcm_token=request.fcm_token,
        device_name=request.device_name,
        android_version=request.android_version,
        app_version=request.app_version,
    )

    if not success:
        logger.error(f"Failed to register device {request.device_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register device",
        )

    logger.info(f"Device {request.device_id} registered successfully")
    return DeviceRegistrationResponse(
        status="registered",
        device_id=request.device_id,
    )

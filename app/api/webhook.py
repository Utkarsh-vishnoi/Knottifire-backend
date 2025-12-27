"""
Webhook API endpoints for receiving notifications from various sources.
Supports native format, Prometheus, Grafana, OCI, and generic payloads.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from app.models.notification import NotificationPayload, WebhookResponse
from app.core.auth import verify_api_key
from app.core.config import config
from app.core.logging import get_logger
from app.queue.sqlite_queue import SQLiteQueue
from app.adapters import get_global_registry
from typing import Dict, Any, List
import json


logger = get_logger("api.webhook")
router = APIRouter()

# Queue instance (initialized in main.py, accessed as dependency)
_queue_instance: SQLiteQueue = None


def get_queue() -> SQLiteQueue:
    """Dependency to get queue instance."""
    return _queue_instance


def set_queue(queue: SQLiteQueue) -> None:
    """Set queue instance (called from main.py)."""
    global _queue_instance
    _queue_instance = queue


def _process_webhook(
    raw_payload: Dict[str, Any],
    queue: SQLiteQueue,
    source_type: str = None
) -> Dict[str, Any]:
    """
    Shared helper to process webhook with adapter transformation.

    Args:
        raw_payload: Raw JSON payload from webhook
        queue: Queue instance
        source_type: Explicit source type (None for auto-detect)

    Returns:
        Response dict with status and message_ids

    Raises:
        HTTPException: On transformation or enqueue failures
    """
    # Validate FCM token configured
    if not config.FCM_DEVICE_TOKEN:
        logger.error("FCM_DEVICE_TOKEN not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FCM device token not configured on backend",
        )

    # Get adapter registry
    registry = get_global_registry()

    try:
        # Transform payload(s) using appropriate adapter
        results = registry.transform(raw_payload, source_type=source_type)

        message_ids = []
        already_exists_count = 0

        # Enqueue each transformed notification (handles batch adapters)
        for result in results:
            payload = result.payload
            metadata = result.metadata
            raw_payload_json = result.raw_payload

            # Get TTL for this priority
            retry_config = config.RETRY_CONFIG.get(payload.priority, config.RETRY_CONFIG["info"])
            ttl_seconds = retry_config["ttl"]

            # Enqueue with raw payload for debugging
            is_new = queue.enqueue(
                message_id=payload.message_id,
                priority=payload.priority,
                payload=json.dumps(payload.model_dump()),
                fcm_token=config.FCM_DEVICE_TOKEN,
                ttl_seconds=ttl_seconds,
                raw_payload=raw_payload_json,
            )

            message_ids.append(payload.message_id)

            if not is_new:
                already_exists_count += 1

            # Log transformation details
            logger.info(
                f"Enqueued message {payload.message_id} from {metadata.source_type}",
                extra={
                    "message_id": payload.message_id,
                    "priority": payload.priority,
                    "source_type": metadata.source_type,
                    "detected": metadata.detected,
                    "batch_index": metadata.batch_index,
                    "is_new": is_new
                }
            )

            if metadata.warnings:
                logger.warning(
                    f"Transformation warnings for {payload.message_id}: {metadata.warnings}",
                    extra={"message_id": payload.message_id}
                )

        # Return response
        return {
            "status": "queued",
            "count": len(message_ids),
            "message_ids": message_ids,
            "already_exists_count": already_exists_count,
            "source_type": results[0].metadata.source_type if results else "unknown"
        }

    except ValueError as e:
        logger.error(f"Transformation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Transformation failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}"
        )


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    _: str = Depends(verify_api_key),
    queue: SQLiteQueue = Depends(get_queue),
):
    """
    Legacy webhook endpoint with auto-detection.

    Supports both:
    - Native canonical format (backward compatible)
    - Auto-detection of Prometheus/Grafana/OCI/Generic formats

    For best performance, use explicit endpoints like /webhook/prometheus
    """
    raw_payload = await request.json()

    logger.info("Received webhook on legacy endpoint (auto-detect mode)")

    result = _process_webhook(raw_payload, queue, source_type=None)

    # Backward compatibility: if native format with single message, return old format
    if result["source_type"] == "native" and result["count"] == 1:
        return WebhookResponse(
            status="queued",
            message_id=result["message_ids"][0],
            already_exists=(result["already_exists_count"] > 0)
        )

    # New format for batch or non-native
    return result


@router.post("/webhook/native")
async def receive_webhook_native(
    request: Request,
    _: str = Depends(verify_api_key),
    queue: SQLiteQueue = Depends(get_queue),
):
    """
    Native canonical format webhook endpoint (explicit).

    Use this endpoint when you're already sending in canonical format.
    Faster than auto-detect endpoint.
    """
    raw_payload = await request.json()
    logger.info("Received native format webhook")
    return _process_webhook(raw_payload, queue, source_type="native")


@router.post("/webhook/prometheus")
async def receive_webhook_prometheus(
    request: Request,
    _: str = Depends(verify_api_key),
    queue: SQLiteQueue = Depends(get_queue),
):
    """
    Prometheus Alertmanager webhook endpoint.

    Handles Prometheus Alertmanager webhook payloads.
    Supports batch processing (multiple alerts per webhook).
    """
    raw_payload = await request.json()
    logger.info("Received Prometheus Alertmanager webhook")
    return _process_webhook(raw_payload, queue, source_type="prometheus")


@router.post("/webhook/grafana")
async def receive_webhook_grafana(
    request: Request,
    _: str = Depends(verify_api_key),
    queue: SQLiteQueue = Depends(get_queue),
):
    """
    Grafana alert webhook endpoint.

    Handles Grafana alert webhook payloads.
    Supports batch processing (multiple alerts per webhook).
    """
    raw_payload = await request.json()
    logger.info("Received Grafana alert webhook")
    return _process_webhook(raw_payload, queue, source_type="grafana")


@router.post("/webhook/oci")
async def receive_webhook_oci(
    request: Request,
    _: str = Depends(verify_api_key),
    queue: SQLiteQueue = Depends(get_queue),
):
    """
    Oracle Cloud Infrastructure (OCI) Monitoring webhook endpoint.

    Handles OCI Monitoring alarm webhooks.
    Single alarm per webhook (no batch processing).
    """
    raw_payload = await request.json()
    logger.info("Received OCI Monitoring webhook")
    return _process_webhook(raw_payload, queue, source_type="oci")


@router.post("/webhook/generic")
async def receive_webhook_generic(
    request: Request,
    _: str = Depends(verify_api_key),
    queue: SQLiteQueue = Depends(get_queue),
):
    """
    Generic webhook endpoint with auto-detection fallback.

    Attempts to detect source type, falls back to generic adapter.
    Use this for custom or unknown webhook formats.
    """
    raw_payload = await request.json()
    logger.info("Received webhook on generic endpoint (auto-detect)")
    return _process_webhook(raw_payload, queue, source_type=None)

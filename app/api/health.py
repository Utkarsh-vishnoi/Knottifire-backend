"""
Health check endpoint for monitoring.
"""

from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from app.models.notification import HealthResponse
from app.core.logging import get_logger
from app.queue.sqlite_queue import SQLiteQueue
from app.queue.worker import get_worker


logger = get_logger("api.health")
router = APIRouter()

# Queue instance (shared with other APIs)
_queue_instance: SQLiteQueue = None


def get_queue() -> SQLiteQueue:
    """Dependency to get queue instance."""
    return _queue_instance


def set_queue(queue: SQLiteQueue) -> None:
    """Set queue instance (called from main.py)."""
    global _queue_instance
    _queue_instance = queue


@router.get("/health", response_model=HealthResponse)
async def health_check(queue: SQLiteQueue = Depends(get_queue)) -> HealthResponse:
    """
    Health check endpoint.

    Returns:
    - Queue depth and age
    - Worker alive status
    - Dead letter count
    - Overall status (healthy/degraded)
    """
    stats = queue.get_stats()
    worker = get_worker()

    # Determine overall status
    is_healthy = (
        stats["total"] < 100 and  # Queue not backed up
        (worker.is_alive() if worker else False)  # Worker running
    )

    status = "healthy" if is_healthy else "degraded"

    worker_info = {
        "alive": worker.is_alive() if worker else False,
        "last_run": datetime.fromtimestamp(worker.last_run, tz=timezone.utc).isoformat() if (worker and worker.last_run) else None,
    }

    return HealthResponse(
        status=status,
        timestamp=datetime.now(timezone.utc).isoformat(),
        queue={
            "total": stats["total"],
            "by_priority": stats["by_priority"],
            "oldest_message_age_seconds": stats["oldest_message_age_seconds"],
        },
        worker=worker_info,
        dead_letter={
            "count": stats["dead_letter_count"],
        },
    )

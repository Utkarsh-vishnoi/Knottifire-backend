"""
Main FastAPI application.
Initializes queue, worker, and API endpoints.
"""

import asyncio
import firebase_admin
from firebase_admin import credentials
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.core.config import config
from app.core.logging import setup_logging, get_logger
from app.queue.sqlite_queue import SQLiteQueue
from app.queue.worker import NotificationWorker, set_worker
from app.api import webhook, ack, health, devices


# Setup logging
setup_logging(config.LOG_LEVEL)
logger = get_logger("main")


# Global queue instance
queue: SQLiteQueue = None
worker_task: asyncio.Task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown.
    Initializes Firebase, queue, and worker.
    """
    global queue, worker_task

    # Startup
    logger.info("Starting notification system backend")

    # Initialize Firebase Admin SDK
    try:
        cred = credentials.Certificate(config.FCM_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        logger.warning("Backend will run but FCM sends will fail")

    # Initialize queue
    queue = SQLiteQueue(config.DATABASE_PATH)

    # Share queue instance with API routers
    webhook.set_queue(queue)
    ack.set_queue(queue)
    health.set_queue(queue)
    devices.set_queue(queue)

    # Initialize and start worker
    worker = NotificationWorker(queue)
    set_worker(worker)
    worker_task = asyncio.create_task(worker.start())
    logger.info("Background worker started")

    yield

    # Shutdown
    logger.info("Shutting down notification system backend")
    if worker:
        worker.stop()
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    if queue:
        queue.close()


# Create FastAPI app
app = FastAPI(
    title="Notification System Backend",
    description="Webhook-driven notification delivery system",
    version="1.0.0",
    lifespan=lifespan,
)

# Include API routers
app.include_router(webhook.router, tags=["webhook"])
app.include_router(ack.router, tags=["ack"])
app.include_router(health.router, tags=["health"])
app.include_router(devices.router, tags=["devices"])


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "Notification System Backend",
        "version": "1.0.0",
        "endpoints": {
            "webhook": "POST /webhook",
            "ack": "POST /ack",
            "health": "GET /health",
            "devices": "POST /devices/register",
            "docs": "GET /docs",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,  # Development only
        log_level=config.LOG_LEVEL.lower(),
    )

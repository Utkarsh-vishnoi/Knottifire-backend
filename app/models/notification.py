"""
Notification data models.
Defines the contract for notifications across all system components.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime
import uuid


class NotificationPayload(BaseModel):
    """
    Global notification schema - source of truth.
    All webhooks must conform to this exact structure.
    """
    version: str = Field(..., pattern="^1\\.0$")
    message_id: str = Field(..., description="UUID v4 for deduplication")
    title: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=1, max_length=500)
    priority: str = Field(..., pattern="^(critical|important|info|silent)$")
    tags: List[str] = Field(..., max_length=10)
    source: str = Field(..., min_length=1, max_length=50)
    timestamp: str = Field(..., description="ISO 8601 timestamp with timezone")

    @field_validator('message_id')
    @classmethod
    def validate_message_id(cls, v: str) -> str:
        """Ensure message_id is valid UUID v4."""
        try:
            uuid.UUID(v, version=4)
        except ValueError:
            raise ValueError("message_id must be a valid UUID v4")
        return v

    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """Ensure each tag is valid."""
        for tag in v:
            if len(tag) > 50:
                raise ValueError("Each tag must be max 50 characters")
        return v

    @field_validator('timestamp')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Ensure timestamp is valid ISO 8601."""
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError("timestamp must be valid ISO 8601 format")
        return v


class WebhookResponse(BaseModel):
    """Response returned by webhook endpoint."""
    status: str = "queued"
    message_id: str
    already_exists: bool = False


class AckRequest(BaseModel):
    """Acknowledgment sent by Android app after successful delivery."""
    message_id: str
    device_id: str = Field(..., description="Unique device identifier")
    device_timestamp: str = Field(..., description="ISO 8601 timestamp from device")

    @field_validator('message_id')
    @classmethod
    def validate_message_id(cls, v: str) -> str:
        """Ensure message_id is valid UUID v4."""
        try:
            uuid.UUID(v, version=4)
        except ValueError:
            raise ValueError("message_id must be a valid UUID v4")
        return v


class AckResponse(BaseModel):
    """Response returned by ACK endpoint."""
    status: str = "acknowledged"
    message_id: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    queue: dict
    worker: dict
    dead_letter: dict


class DeviceRegistrationRequest(BaseModel):
    """Device registration request from Android app."""
    device_id: str = Field(..., min_length=1, description="Unique device identifier")
    fcm_token: str = Field(..., min_length=1, description="Firebase Cloud Messaging token")
    device_name: Optional[str] = Field(None, max_length=100, description="Human-readable device name")
    android_version: Optional[int] = Field(None, ge=21, le=50, description="Android API level")
    app_version: Optional[str] = Field(None, max_length=20, description="App version string")


class DeviceRegistrationResponse(BaseModel):
    """Response returned by device registration endpoint."""
    status: str = "registered"
    device_id: str

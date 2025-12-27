"""
Native adapter for payloads already in canonical format.
Passthrough adapter with validation.
"""

from typing import Dict, Any, List
from pydantic import ValidationError
from app.adapters.base import BaseAdapter, TransformationResult
from app.models.notification import NotificationPayload


class NativeAdapter(BaseAdapter):
    """
    Adapter for native canonical format payloads.

    Performs validation and passthrough - no transformation needed.
    """

    SOURCE_TYPE = "native"
    SUPPORTS_BATCH = False
    DETECTION_PRIORITY = 10  # Highest priority (check first)

    def can_handle(self, raw_payload: Dict[str, Any]) -> bool:
        """
        Detect native format by checking for exact schema match.

        Args:
            raw_payload: Raw webhook payload

        Returns:
            True if payload matches canonical schema
        """
        # Check for required fields in canonical format
        required_fields = {"version", "message_id", "title", "body", "priority", "tags", "source", "timestamp"}

        if not all(field in raw_payload for field in required_fields):
            return False

        # Check version field
        if raw_payload.get("version") != "1.0":
            return False

        # Try to validate (quick check without raising)
        try:
            NotificationPayload(**raw_payload)
            return True
        except ValidationError:
            return False

    def transform(self, raw_payload: Dict[str, Any]) -> List[TransformationResult]:
        """
        Validate and passthrough native format payload.

        Args:
            raw_payload: Raw webhook JSON (must be canonical format)

        Returns:
            Single TransformationResult with validated payload

        Raises:
            ValidationError: If payload doesn't match canonical schema
        """
        self._reset_tracking()
        self._log_transformation("Validating native format payload")

        try:
            # Validate using Pydantic model
            payload = NotificationPayload(**raw_payload)
            self._log_transformation("Payload validated successfully (no transformation needed)")

            result = self._build_result(
                payload=payload,
                raw_payload=raw_payload,
                detected=False,  # Will be overridden if auto-detected
                batch_index=None
            )

            return [result]

        except ValidationError as e:
            self.logger.error(f"Native payload validation failed: {e}")
            raise ValueError(f"Invalid native payload: {e}")

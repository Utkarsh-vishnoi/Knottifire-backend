"""
Generic fallback adapter for unknown webhook formats.
Best-effort transformation with flexible field extraction.
"""

from typing import Dict, Any, List
from app.adapters.base import BaseAdapter, TransformationResult
from app.models.notification import NotificationPayload


class GenericAdapter(BaseAdapter):
    """
    Fallback adapter for unknown/custom webhook formats.

    Attempts to extract notification fields using common field name variations.
    Always returns True for can_handle (catch-all).
    """

    SOURCE_TYPE = "generic"
    SUPPORTS_BATCH = False
    DETECTION_PRIORITY = 100  # Lowest priority (checked last)

    # Common field name variations to try
    TITLE_FIELDS = ["title", "subject", "summary", "name", "alertname", "alert_name", "heading"]
    BODY_FIELDS = ["body", "description", "message", "text", "details", "content", "msg"]
    PRIORITY_FIELDS = ["priority", "severity", "level", "importance", "criticality"]
    TAGS_FIELDS = ["tags", "labels", "categories", "keywords"]
    SOURCE_FIELDS = ["source", "origin", "from", "sender", "system", "service"]
    TIMESTAMP_FIELDS = ["timestamp", "time", "created_at", "date", "startsAt", "eventTime"]

    # Severity mapping (generic)
    SEVERITY_MAP = {
        "critical": "critical",
        "error": "critical",
        "high": "critical",
        "1": "critical",
        "warning": "important",
        "warn": "important",
        "medium": "important",
        "2": "important",
        "info": "info",
        "information": "info",
        "low": "info",
        "3": "info",
        "debug": "silent",
        "trace": "silent",
        "4": "silent",
    }

    def can_handle(self, raw_payload: Dict[str, Any]) -> bool:
        """
        Generic adapter always returns True (fallback/catch-all).

        Args:
            raw_payload: Raw webhook payload

        Returns:
            Always True
        """
        return True  # Catch-all

    def transform(self, raw_payload: Dict[str, Any]) -> List[TransformationResult]:
        """
        Best-effort transformation of arbitrary JSON to canonical format.

        Tries multiple field name variations for each canonical field.
        Uses sensible defaults if fields not found.

        Args:
            raw_payload: Raw webhook JSON

        Returns:
            Single TransformationResult

        Raises:
            ValueError: If minimum required fields cannot be extracted
        """
        self._reset_tracking()
        self._log_transformation("Starting generic payload transformation")

        # Extract fields using helper methods with multiple fallbacks
        title = self._extract_title(raw_payload, *self.TITLE_FIELDS, default="Notification")
        body = self._extract_body(raw_payload, *self.BODY_FIELDS, default="")
        priority = self._extract_priority(raw_payload, self.SEVERITY_MAP, *self.PRIORITY_FIELDS, default="info")
        timestamp = self._extract_timestamp(raw_payload, *self.TIMESTAMP_FIELDS)
        tags = self._extract_tags(
            raw_payload,
            *self.TAGS_FIELDS,
            additional_tags=["generic"],
            max_tags=10
        )

        # Extract source
        source_value = self._extract_title(raw_payload, *self.SOURCE_FIELDS, max_length=50, default="generic")

        # Generate random UUID (no stable source ID available)
        message_id = self._generate_message_id(raw_payload, source_id=None)

        # Build canonical payload
        try:
            payload = NotificationPayload(
                version="1.0",
                message_id=message_id,
                title=title,
                body=body,
                priority=priority,
                tags=tags,
                source=source_value,
                timestamp=timestamp
            )

            self._log_transformation("Generic transformation completed successfully")

            result = self._build_result(
                payload=payload,
                raw_payload=raw_payload,
                detected=False,  # Will be overridden if auto-detected
                batch_index=None
            )

            return [result]

        except Exception as e:
            self.logger.error(f"Generic transformation failed: {e}")
            raise ValueError(f"Failed to transform generic payload: {e}")

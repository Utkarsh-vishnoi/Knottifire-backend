"""
Base adapter class and interfaces for webhook payload transformation.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.models.notification import NotificationPayload
from app.core.logging import get_logger
from app.adapters import utils


class AdapterMetadata(BaseModel):
    """Metadata about the transformation process."""
    source_type: str
    detected: bool  # Whether source was auto-detected or explicit
    transformations: List[str]  # List of transformation steps applied
    warnings: List[str] = []  # Non-fatal issues during transformation
    batch_index: Optional[int] = None  # Index if part of batch (0-based)


class TransformationResult(BaseModel):
    """Result of payload transformation."""
    payload: NotificationPayload
    metadata: AdapterMetadata
    raw_payload: str  # Original JSON for database storage


class BaseAdapter(ABC):
    """
    Abstract base class for webhook payload adapters.

    Each adapter transforms source-specific webhook payloads
    into our canonical NotificationPayload format.
    """

    # Source identifier (e.g., "prometheus", "grafana", "oci")
    SOURCE_TYPE: str = "unknown"

    # Whether this adapter supports batch processing (multiple notifications per webhook)
    SUPPORTS_BATCH: bool = False

    def __init__(self):
        self.logger = get_logger(f"adapters.{self.SOURCE_TYPE}")
        self.transformations: List[str] = []
        self.warnings: List[str] = []

    @abstractmethod
    def can_handle(self, raw_payload: Dict[str, Any]) -> bool:
        """
        Detect if this adapter can handle the given payload.

        Used for auto-detection in generic endpoint.
        Should check for source-specific markers.

        Args:
            raw_payload: Raw JSON dict from webhook

        Returns:
            True if this adapter can handle the payload
        """
        pass

    @abstractmethod
    def transform(self, raw_payload: Dict[str, Any]) -> List[TransformationResult]:
        """
        Transform raw payload into canonical NotificationPayload(s).

        Args:
            raw_payload: Raw JSON dict from webhook

        Returns:
            List of TransformationResult (single item for non-batch adapters)

        Raises:
            ValueError: If transformation fails due to missing required fields
            ValidationError: If Pydantic validation fails
        """
        pass

    def supports_batch(self) -> bool:
        """Return whether this adapter creates multiple notifications from one webhook."""
        return self.SUPPORTS_BATCH

    # Helper methods available to all adapters

    def _extract_title(
        self,
        raw_payload: Dict[str, Any],
        *paths: str,
        max_length: int = 100,
        default: str = "Notification"
    ) -> str:
        """
        Extract title from multiple possible paths, truncate if needed.

        Args:
            raw_payload: Source payload
            *paths: Ordered list of paths to try (e.g., "alerts.0.annotations.summary")
            max_length: Maximum length (default 100)
            default: Default value if no path succeeds

        Returns:
            Extracted and truncated title
        """
        value = utils.extract_nested_field(raw_payload, *paths, default=default)
        if value is None:
            return default

        title = str(value)
        if len(title) > max_length:
            self._log_warning(f"Title truncated from {len(title)} to {max_length} characters")
            return utils.truncate_field(title, max_length)

        return title

    def _extract_body(
        self,
        raw_payload: Dict[str, Any],
        *paths: str,
        max_length: int = 500,
        default: str = ""
    ) -> str:
        """
        Extract body from multiple possible paths, truncate if needed.

        Args:
            raw_payload: Source payload
            *paths: Ordered list of paths to try
            max_length: Maximum length (default 500)
            default: Default value if no path succeeds

        Returns:
            Extracted and truncated body
        """
        value = utils.extract_nested_field(raw_payload, *paths, default=default)
        if value is None:
            return default

        body = str(value)
        if len(body) > max_length:
            self._log_warning(f"Body truncated from {len(body)} to {max_length} characters")
            return utils.truncate_field(body, max_length)

        return body

    def _extract_priority(
        self,
        raw_payload: Dict[str, Any],
        severity_map: Dict[str, str],
        *paths: str,
        default: str = "info"
    ) -> str:
        """
        Extract and map severity to our priority levels.

        Args:
            raw_payload: Source payload
            severity_map: Mapping from source severity to our priority
            *paths: Ordered list of paths to try
            default: Default priority if not found

        Returns:
            One of: critical, important, info, silent
        """
        severity = utils.extract_nested_field(raw_payload, *paths)
        priority = utils.map_severity_to_priority(severity, severity_map, default)

        if priority != default:
            self._log_transformation(f"Mapped severity '{severity}' to priority '{priority}'")

        return priority

    def _extract_timestamp(
        self,
        raw_payload: Dict[str, Any],
        *paths: str
    ) -> str:
        """
        Extract and normalize timestamp to ISO 8601.

        Args:
            raw_payload: Source payload
            *paths: Ordered list of paths to try

        Returns:
            ISO 8601 formatted timestamp with timezone

        Raises:
            ValueError: If no valid timestamp found
        """
        timestamp_value = utils.extract_nested_field(raw_payload, *paths)

        if timestamp_value is None:
            # Use current time as fallback
            from datetime import datetime, timezone
            self._log_warning("No timestamp found in payload, using current time")
            return datetime.now(timezone.utc).isoformat()

        try:
            iso_timestamp = utils.parse_timestamp(timestamp_value)
            self._log_transformation(f"Parsed timestamp: {timestamp_value} → {iso_timestamp}")
            return iso_timestamp
        except ValueError as e:
            self._log_warning(f"Failed to parse timestamp '{timestamp_value}': {e}, using current time")
            from datetime import datetime, timezone
            return datetime.now(timezone.utc).isoformat()

    def _generate_message_id(
        self,
        raw_payload: Dict[str, Any],
        source_id: Optional[str] = None
    ) -> str:
        """
        Generate message ID for deduplication.

        If source_id is provided, generates deterministic UUID v5.
        Otherwise, generates random UUID v4.

        Args:
            raw_payload: Source payload (for fallback generation)
            source_id: Source-specific stable identifier (optional)

        Returns:
            UUID string
        """
        if source_id:
            message_id = utils.generate_uuid_from_source_id(source_id, namespace=self.SOURCE_TYPE)
            self._log_transformation(f"Generated deterministic UUID from source_id: {source_id[:20]}...")
            return message_id
        else:
            message_id = utils.generate_random_uuid()
            self._log_transformation("Generated random UUID (no source_id available)")
            return message_id

    def _extract_tags(
        self,
        raw_payload: Dict[str, Any],
        *paths: str,
        additional_tags: Optional[List[str]] = None,
        exclude_keys: Optional[List[str]] = None,
        max_tags: int = 10,
        max_tag_length: int = 50
    ) -> List[str]:
        """
        Extract tags from payload, enforce limits.

        Args:
            raw_payload: Source payload
            *paths: Ordered list of paths to try (dicts will be flattened to tags)
            additional_tags: Extra tags to always include
            exclude_keys: Keys to exclude when flattening
            max_tags: Maximum number of tags
            max_tag_length: Maximum length per tag

        Returns:
            List of valid tags
        """
        tags = []

        # Add additional tags first
        if additional_tags:
            tags.extend(additional_tags)

        # Try to extract tags from paths
        for path in paths:
            value = utils.extract_nested_field(raw_payload, path)

            if value is None:
                continue

            if isinstance(value, list):
                # List of strings → direct tags
                for item in value:
                    if isinstance(item, str) and len(item) <= max_tag_length:
                        tags.append(item)
            elif isinstance(value, dict):
                # Dict → flatten to key:value pairs
                flattened = utils.flatten_dict_to_tags(
                    value,
                    exclude_keys=exclude_keys,
                    max_tags=max_tags - len(tags),
                    max_tag_length=max_tag_length
                )
                tags.extend(flattened)
            elif isinstance(value, str):
                # String → single tag
                if len(value) <= max_tag_length:
                    tags.append(value)

            if len(tags) >= max_tags:
                break

        # Enforce max_tags limit
        final_tags = tags[:max_tags]

        if len(tags) > max_tags:
            self._log_warning(f"Tags truncated from {len(tags)} to {max_tags}")

        return final_tags

    def _log_transformation(self, step: str):
        """Record transformation step for metadata."""
        self.transformations.append(step)
        self.logger.debug(f"[{self.SOURCE_TYPE}] Transformation: {step}")

    def _log_warning(self, warning: str):
        """Record non-fatal warning."""
        self.warnings.append(warning)
        self.logger.warning(f"[{self.SOURCE_TYPE}] Warning: {warning}")

    def _reset_tracking(self):
        """Reset transformation tracking (call before each transform)."""
        self.transformations = []
        self.warnings = []

    def _build_result(
        self,
        payload: NotificationPayload,
        raw_payload: Dict[str, Any],
        detected: bool = False,
        batch_index: Optional[int] = None
    ) -> TransformationResult:
        """
        Build TransformationResult with metadata.

        Args:
            payload: Transformed canonical payload
            raw_payload: Original webhook JSON
            detected: Whether source was auto-detected
            batch_index: Index in batch if applicable

        Returns:
            TransformationResult
        """
        metadata = AdapterMetadata(
            source_type=self.SOURCE_TYPE,
            detected=detected,
            transformations=self.transformations.copy(),
            warnings=self.warnings.copy(),
            batch_index=batch_index
        )

        return TransformationResult(
            payload=payload,
            metadata=metadata,
            raw_payload=utils.serialize_raw_payload(raw_payload)
        )

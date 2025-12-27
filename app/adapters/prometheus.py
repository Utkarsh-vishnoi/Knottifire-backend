"""
Prometheus Alertmanager webhook adapter.
Supports batch processing (multiple alerts per webhook).
"""

from typing import Dict, Any, List
from app.adapters.base import BaseAdapter, TransformationResult
from app.models.notification import NotificationPayload


class PrometheusAdapter(BaseAdapter):
    """
    Adapter for Prometheus Alertmanager webhook payloads.

    Supports batch processing - creates one notification per alert in the alerts array.

    Payload structure:
    {
      "version": "4",
      "groupKey": "...",
      "status": "firing",
      "alerts": [
        {
          "status": "firing",
          "labels": {"alertname": "...", "severity": "critical", ...},
          "annotations": {"summary": "...", "description": "..."},
          "startsAt": "2025-12-26T10:00:00.123Z",
          "fingerprint": "abc123..."
        }
      ],
      "commonLabels": {...}
    }
    """

    SOURCE_TYPE = "prometheus"
    SUPPORTS_BATCH = True
    DETECTION_PRIORITY = 30

    # Severity mapping (Prometheus → our priority)
    SEVERITY_MAP = {
        "critical": "critical",
        "warning": "important",
        "info": "info",
        "none": "silent",
    }

    def can_handle(self, raw_payload: Dict[str, Any]) -> bool:
        """
        Detect Prometheus Alertmanager payload.

        Checks for:
        - version field (typically "4")
        - groupKey field
        - alerts array with startsAt timestamp

        Args:
            raw_payload: Raw webhook payload

        Returns:
            True if payload looks like Prometheus Alertmanager
        """
        # Check for required Prometheus-specific fields
        if "version" not in raw_payload:
            return False

        if "groupKey" not in raw_payload:
            return False

        if "alerts" not in raw_payload or not isinstance(raw_payload.get("alerts"), list):
            return False

        # Check if alerts have Prometheus-specific structure
        alerts = raw_payload["alerts"]
        if len(alerts) > 0:
            first_alert = alerts[0]
            # Prometheus alerts have startsAt in RFC3339 format
            if "startsAt" in first_alert and "fingerprint" in first_alert:
                return True

        return False

    def transform(self, raw_payload: Dict[str, Any]) -> List[TransformationResult]:
        """
        Transform Prometheus Alertmanager payload to canonical format.

        Creates one notification per alert in the alerts array (batch processing).

        Args:
            raw_payload: Raw Prometheus webhook JSON

        Returns:
            List of TransformationResult (one per alert)

        Raises:
            ValueError: If alerts array is empty or malformed
        """
        self._reset_tracking()
        self._log_transformation("Starting Prometheus Alertmanager transformation")

        # Extract alerts array
        alerts = raw_payload.get("alerts", [])
        if not alerts:
            raise ValueError("Prometheus payload has no alerts")

        # Extract common labels (shared across all alerts in group)
        common_labels = raw_payload.get("commonLabels", {})
        group_key = raw_payload.get("groupKey", "")

        results = []

        # Process each alert individually
        for index, alert in enumerate(alerts):
            try:
                result = self._transform_alert(alert, common_labels, group_key, index)
                results.append(result)
                self._log_transformation(f"Transformed alert {index + 1}/{len(alerts)}")
            except Exception as e:
                self._log_warning(f"Failed to transform alert {index}: {e}")
                # Continue with other alerts instead of failing completely
                continue

        if not results:
            raise ValueError("Failed to transform any alerts from Prometheus payload")

        self._log_transformation(f"Prometheus batch transformation completed: {len(results)} notifications")
        return results

    def _transform_alert(
        self,
        alert: Dict[str, Any],
        common_labels: Dict[str, Any],
        group_key: str,
        batch_index: int
    ) -> TransformationResult:
        """
        Transform a single Prometheus alert to canonical format.

        Args:
            alert: Single alert from alerts array
            common_labels: Labels common to all alerts in group
            group_key: Prometheus group key
            batch_index: Index of this alert in the batch

        Returns:
            TransformationResult for this alert
        """
        # Extract fingerprint for deterministic UUID
        fingerprint = alert.get("fingerprint", "")
        message_id = self._generate_message_id(alert, source_id=fingerprint)

        # Extract title: prefer annotations.summary, fallback to labels.alertname
        title = self._extract_title(
            alert,
            "annotations.summary",
            "labels.alertname",
            "labels.alert",
            default="Prometheus Alert"
        )

        # Extract body: prefer annotations.description, fallback to annotations.summary
        body = self._extract_body(
            alert,
            "annotations.description",
            "annotations.summary",
            "annotations.message",
            default=""
        )

        # Extract priority from labels.severity
        priority = self._extract_priority(
            alert,
            self.SEVERITY_MAP,
            "labels.severity",
            default="important"  # Prometheus default
        )

        # Extract timestamp from startsAt
        timestamp = self._extract_timestamp(alert, "startsAt", "endsAt")

        # Build tags from all labels (both alert-specific and common)
        alert_labels = alert.get("labels", {})
        tags = self._extract_tags(
            alert,
            "labels",
            additional_tags=["prometheus", f"group:{group_key[:30]}"],
            exclude_keys=["severity", "alertname"],  # Already used in title/priority
            max_tags=10
        )

        # Build canonical payload
        payload = NotificationPayload(
            version="1.0",
            message_id=message_id,
            title=title,
            body=body,
            priority=priority,
            tags=tags,
            source="prometheus",
            timestamp=timestamp
        )

        result = self._build_result(
            payload=payload,
            raw_payload=alert,  # Store individual alert, not entire batch
            detected=False,
            batch_index=batch_index
        )

        return result

"""
Oracle Cloud Infrastructure (OCI) Monitoring webhook adapter.
Single alarm per webhook (no batch processing).
"""

from typing import Dict, Any, List
from app.adapters.base import BaseAdapter, TransformationResult
from app.models.notification import NotificationPayload


class OCIAdapter(BaseAdapter):
    """
    Adapter for Oracle Cloud Infrastructure Monitoring alarm webhooks.

    Does not support batch processing - OCI sends one alarm per webhook.

    Payload structure:
    {
      "dedupeKey": "alarm-5db34",
      "title": "High CPU Alert",
      "type": "REPEAT",
      "severity": "CRITICAL",
      "timestampEpochMillis": 1735210800000,
      "timestamp": "2025-12-26T10:00:00Z",
      "alarmMetaData": [
        {
          "id": "ocid1.alarm.oc1...",
          "status": "FIRING",
          "severity": "CRITICAL",
          "namespace": "oci_computeagent",
          "query": "CpuUtilization[1m].mean() > 80",
          "dimensions": [{
            "resourceDisplayName": "web-server-1",
            "region": "us-phoenix-1"
          }],
          "alarmSummary": "CPU usage exceeded threshold"
        }
      ]
    }
    """

    SOURCE_TYPE = "oci"
    SUPPORTS_BATCH = False
    DETECTION_PRIORITY = 20  # Check before Prometheus/Grafana (more specific)

    # Severity mapping (OCI → our priority)
    SEVERITY_MAP = {
        "critical": "critical",
        "error": "critical",
        "warning": "important",
        "info": "info",
    }

    def can_handle(self, raw_payload: Dict[str, Any]) -> bool:
        """
        Detect OCI Monitoring alarm payload.

        Checks for:
        - dedupeKey field
        - alarmMetaData array
        - timestampEpochMillis field

        Args:
            raw_payload: Raw webhook payload

        Returns:
            True if payload looks like OCI Monitoring
        """
        # Check for OCI-specific fields
        if "dedupeKey" not in raw_payload:
            return False

        if "alarmMetaData" not in raw_payload or not isinstance(raw_payload.get("alarmMetaData"), list):
            return False

        if "timestampEpochMillis" not in raw_payload and "timestamp" not in raw_payload:
            return False

        # Additional check: alarmMetaData should have OCI-specific structure
        alarm_meta = raw_payload.get("alarmMetaData", [])
        if len(alarm_meta) > 0:
            first_alarm = alarm_meta[0]
            # OCI alarms have namespace and dimensions
            if "namespace" in first_alarm or "dimensions" in first_alarm:
                return True

        return False

    def transform(self, raw_payload: Dict[str, Any]) -> List[TransformationResult]:
        """
        Transform OCI Monitoring alarm to canonical format.

        Creates single notification (no batch processing).

        Args:
            raw_payload: Raw OCI webhook JSON

        Returns:
            Single-element list with TransformationResult

        Raises:
            ValueError: If required fields are missing
        """
        self._reset_tracking()
        self._log_transformation("Starting OCI Monitoring alarm transformation")

        # Extract dedupeKey for deterministic UUID
        dedupe_key = raw_payload.get("dedupeKey", "")
        if not dedupe_key:
            self._log_warning("Missing dedupeKey, using random UUID")
            message_id = self._generate_message_id(raw_payload, source_id=None)
        else:
            message_id = self._generate_message_id(raw_payload, source_id=dedupe_key)

        # Extract title (OCI provides this directly)
        title = self._extract_title(
            raw_payload,
            "title",
            "alarmMetaData.0.alarmSummary",
            default="OCI Alert"
        )

        # Extract body from alarmMetaData
        alarm_meta = raw_payload.get("alarmMetaData", [])
        if alarm_meta:
            body = self._extract_body(
                alarm_meta[0],
                "alarmSummary",
                "query",
                default=""
            )
        else:
            body = self._extract_body(raw_payload, "body", "message", default="")

        # Extract priority from severity
        priority = self._extract_priority(
            raw_payload,
            self.SEVERITY_MAP,
            "severity",
            "alarmMetaData.0.severity",
            default="important"
        )

        # Extract timestamp (OCI provides both formats)
        timestamp = self._extract_timestamp(
            raw_payload,
            "timestamp",
            "timestampEpochMillis"
        )

        # Build tags from alarmMetaData dimensions + namespace
        tags = ["oci"]

        if alarm_meta:
            first_alarm = alarm_meta[0]

            # Add namespace as tag
            namespace = first_alarm.get("namespace")
            if namespace:
                tags.append(f"namespace:{namespace}")

            # Add dimensions as tags
            dimensions = first_alarm.get("dimensions", [])
            for dim in dimensions:
                if isinstance(dim, dict):
                    for key, value in dim.items():
                        tag = f"{key}:{value}"
                        if len(tag) <= 50:
                            tags.append(tag)

                        if len(tags) >= 10:
                            break

        # Truncate tags if needed
        tags = tags[:10]

        # Build canonical payload
        try:
            payload = NotificationPayload(
                version="1.0",
                message_id=message_id,
                title=title,
                body=body,
                priority=priority,
                tags=tags,
                source="oci",
                timestamp=timestamp
            )

            self._log_transformation("OCI transformation completed successfully")

            result = self._build_result(
                payload=payload,
                raw_payload=raw_payload,
                detected=False,
                batch_index=None  # No batch support
            )

            return [result]

        except Exception as e:
            self.logger.error(f"OCI transformation failed: {e}")
            raise ValueError(f"Failed to transform OCI payload: {e}")

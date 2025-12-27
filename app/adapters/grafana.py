"""
Grafana alert webhook adapter.
Supports batch processing (multiple alerts per webhook).
"""

from typing import Dict, Any, List
from app.adapters.base import BaseAdapter, TransformationResult
from app.models.notification import NotificationPayload


class GrafanaAdapter(BaseAdapter):
    """
    Adapter for Grafana alert webhook payloads.

    Supports batch processing - creates one notification per alert in the alerts array.

    Payload structure:
    {
      "receiver": "webhook",
      "status": "firing",
      "orgId": 1,
      "alerts": [
        {
          "status": "firing",
          "labels": {"alertname": "...", "severity": "warning", ...},
          "annotations": {"summary": "...", "description": "..."},
          "startsAt": "2025-12-26T10:00:00Z",
          "fingerprint": "abc123",
          "dashboardURL": "...",
          "panelURL": "..."
        }
      ]
    }
    """

    SOURCE_TYPE = "grafana"
    SUPPORTS_BATCH = True
    DETECTION_PRIORITY = 40

    # Severity mapping (Grafana → our priority)
    SEVERITY_MAP = {
        "critical": "critical",
        "warning": "important",
        "info": "info",
        "ok": "silent",
        "resolved": "info",  # Resolved alerts are informational
    }

    def can_handle(self, raw_payload: Dict[str, Any]) -> bool:
        """
        Detect Grafana alert payload.

        Checks for:
        - receiver field
        - orgId field
        - alerts array with fingerprint

        Args:
            raw_payload: Raw webhook payload

        Returns:
            True if payload looks like Grafana
        """
        # Check for Grafana-specific fields
        if "receiver" not in raw_payload:
            return False

        if "orgId" not in raw_payload:
            return False

        if "alerts" not in raw_payload or not isinstance(raw_payload.get("alerts"), list):
            return False

        # Check if alerts have Grafana-specific structure
        alerts = raw_payload["alerts"]
        if len(alerts) > 0:
            first_alert = alerts[0]
            # Grafana alerts have fingerprint and may have dashboardURL
            if "fingerprint" in first_alert:
                return True

        return False

    def transform(self, raw_payload: Dict[str, Any]) -> List[TransformationResult]:
        """
        Transform Grafana alert payload to canonical format.

        Creates one notification per alert in the alerts array (batch processing).

        Args:
            raw_payload: Raw Grafana webhook JSON

        Returns:
            List of TransformationResult (one per alert)

        Raises:
            ValueError: If alerts array is empty or malformed
        """
        self._reset_tracking()
        self._log_transformation("Starting Grafana alert transformation")

        # Extract alerts array
        alerts = raw_payload.get("alerts", [])
        if not alerts:
            raise ValueError("Grafana payload has no alerts")

        # Extract common metadata
        org_id = raw_payload.get("orgId", "unknown")
        receiver = raw_payload.get("receiver", "unknown")

        results = []

        # Process each alert individually
        for index, alert in enumerate(alerts):
            try:
                result = self._transform_alert(alert, org_id, receiver, index)
                results.append(result)
                self._log_transformation(f"Transformed alert {index + 1}/{len(alerts)}")
            except Exception as e:
                self._log_warning(f"Failed to transform alert {index}: {e}")
                # Continue with other alerts
                continue

        if not results:
            raise ValueError("Failed to transform any alerts from Grafana payload")

        self._log_transformation(f"Grafana batch transformation completed: {len(results)} notifications")
        return results

    def _transform_alert(
        self,
        alert: Dict[str, Any],
        org_id: Any,
        receiver: str,
        batch_index: int
    ) -> TransformationResult:
        """
        Transform a single Grafana alert to canonical format.

        Args:
            alert: Single alert from alerts array
            org_id: Grafana organization ID
            receiver: Receiver name
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
            default="Grafana Alert"
        )

        # Extract body: prefer annotations.description
        body_text = self._extract_body(
            alert,
            "annotations.description",
            "annotations.summary",
            "annotations.message",
            default=""
        )

        # Append dashboard URL if available
        dashboard_url = alert.get("dashboardURL") or alert.get("panelURL")
        if dashboard_url:
            if body_text:
                body_text += f"\n\nDashboard: {dashboard_url}"
            else:
                body_text = f"Dashboard: {dashboard_url}"
            self._log_transformation("Appended dashboard URL to body")

        # Truncate body if too long (after adding URL)
        if len(body_text) > 500:
            body_text = body_text[:497] + "..."
            self._log_warning("Body truncated after adding dashboard URL")

        # Extract priority from labels.severity OR status
        # First try severity label
        priority = self._extract_priority(
            alert,
            self.SEVERITY_MAP,
            "labels.severity",
            "status",  # fallback: firing=important, resolved=info
            default="important"
        )

        # Extract timestamp from startsAt
        timestamp = self._extract_timestamp(alert, "startsAt", "endsAt")

        # Build tags from labels
        tags = self._extract_tags(
            alert,
            "labels",
            additional_tags=["grafana", f"org:{org_id}"],
            exclude_keys=["severity", "alertname"],  # Already used
            max_tags=10
        )

        # Build canonical payload
        payload = NotificationPayload(
            version="1.0",
            message_id=message_id,
            title=title,
            body=body_text,
            priority=priority,
            tags=tags,
            source="grafana",
            timestamp=timestamp
        )

        result = self._build_result(
            payload=payload,
            raw_payload=alert,  # Store individual alert, not entire batch
            detected=False,
            batch_index=batch_index
        )

        return result

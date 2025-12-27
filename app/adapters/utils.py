"""
Shared utility functions for webhook payload adapters.
"""

import uuid
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import hashlib


def parse_timestamp(value: Any) -> str:
    """
    Parse various timestamp formats to ISO 8601 with timezone.

    Supports:
    - ISO 8601 strings (with or without timezone)
    - RFC 3339 (Prometheus/Grafana)
    - Unix epoch (seconds or milliseconds)
    - datetime objects

    Args:
        value: Timestamp in various formats

    Returns:
        ISO 8601 formatted string with timezone

    Raises:
        ValueError: If timestamp cannot be parsed
    """
    if isinstance(value, str):
        # Already a string, try parsing
        try:
            # Handle 'Z' suffix (UTC indicator)
            timestamp_str = value.replace('Z', '+00:00')
            dt = datetime.fromisoformat(timestamp_str)
            # Ensure timezone aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            raise ValueError(f"Cannot parse timestamp string: {value}")

    elif isinstance(value, (int, float)):
        # Unix timestamp (detect if milliseconds or seconds)
        if value > 1e12:  # Likely milliseconds
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        else:  # Likely seconds
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        return dt.isoformat()

    elif isinstance(value, datetime):
        # datetime object
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    else:
        raise ValueError(f"Unsupported timestamp type: {type(value)}")


def generate_uuid_from_source_id(source_id: str, namespace: Optional[str] = None) -> str:
    """
    Generate deterministic UUID v5 from source ID string.

    This enables deduplication: same source ID → same message_id

    Args:
        source_id: Source-specific identifier (e.g., Prometheus fingerprint, OCI dedupeKey)
        namespace: Optional namespace string (default: "notification-system")

    Returns:
        UUID v5 as string
    """
    # Use DNS namespace as base, mix with our namespace
    namespace_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, namespace or "notification-system")
    return str(uuid.uuid5(namespace_uuid, source_id))


def generate_random_uuid() -> str:
    """
    Generate random UUID v4.

    Used for sources without stable identifiers.

    Returns:
        UUID v4 as string
    """
    return str(uuid.uuid4())


def truncate_field(value: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to max length, adding ellipsis if truncated.

    Args:
        value: String to truncate
        max_length: Maximum length (including suffix)
        suffix: Suffix to add if truncated (default "...")

    Returns:
        Truncated string
    """
    if len(value) <= max_length:
        return value

    return value[:max_length - len(suffix)] + suffix


def extract_nested_field(
    data: Dict[str, Any],
    *paths: str,
    default: Optional[Any] = None
) -> Optional[Any]:
    """
    Extract value from nested dict using multiple fallback paths.

    Supports dot notation for nested access: "alerts.0.labels.severity"

    Args:
        data: Source dictionary
        *paths: Ordered list of paths to try (e.g., "alerts[0].summary", "title")
        default: Default value if all paths fail

    Returns:
        Extracted value or default

    Example:
        extract_nested_field(data, "alerts.0.labels.severity", "severity", default="info")
    """
    for path in paths:
        try:
            value = data
            # Split path by dots and handle array indices
            parts = path.replace('[', '.').replace(']', '').split('.')

            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                elif isinstance(value, list):
                    try:
                        index = int(part)
                        value = value[index]
                    except (ValueError, IndexError):
                        value = None
                        break
                else:
                    value = None
                    break

            if value is not None:
                return value

        except (KeyError, TypeError, IndexError):
            continue

    return default


def flatten_dict_to_tags(
    data: Dict[str, Any],
    prefix: str = "",
    exclude_keys: Optional[List[str]] = None,
    max_tags: int = 10,
    max_tag_length: int = 50
) -> List[str]:
    """
    Flatten nested dictionary to key:value tag pairs.

    Args:
        data: Dictionary to flatten
        prefix: Prefix for nested keys
        exclude_keys: Keys to exclude from tags
        max_tags: Maximum number of tags to return
        max_tag_length: Maximum length per tag

    Returns:
        List of "key:value" tag strings

    Example:
        {"env": "prod", "labels": {"team": "platform"}}
        → ["env:prod", "team:platform"]
    """
    tags = []
    exclude_keys = exclude_keys or []

    def _flatten(obj: Any, key_prefix: str = ""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in exclude_keys:
                    continue

                full_key = f"{key_prefix}.{key}" if key_prefix else key

                if isinstance(value, (dict, list)):
                    _flatten(value, full_key)
                elif value is not None:
                    tag = f"{full_key}:{value}"
                    if len(tag) <= max_tag_length:
                        tags.append(tag)
                    if len(tags) >= max_tags:
                        return

        elif isinstance(obj, list):
            # For lists, only process if they contain simple values
            for item in obj:
                if isinstance(item, (str, int, float, bool)):
                    tag = f"{key_prefix}:{item}"
                    if len(tag) <= max_tag_length:
                        tags.append(tag)
                    if len(tags) >= max_tags:
                        return

    _flatten(data, prefix)
    return tags[:max_tags]


def serialize_raw_payload(payload: Dict[str, Any]) -> str:
    """
    Serialize payload dict to JSON string for database storage.

    Args:
        payload: Raw webhook payload

    Returns:
        JSON string
    """
    return json.dumps(payload, separators=(',', ':'))  # Compact JSON


def map_severity_to_priority(
    severity: Optional[str],
    severity_map: Dict[str, str],
    default: str = "info"
) -> str:
    """
    Map source severity value to canonical priority.

    Args:
        severity: Source severity string (case-insensitive)
        severity_map: Mapping from source severity to priority
        default: Default priority if no match

    Returns:
        One of: critical, important, info, silent
    """
    if not severity:
        return default

    # Normalize to lowercase for case-insensitive matching
    severity_lower = str(severity).lower()

    # Try exact match first
    if severity_lower in severity_map:
        return severity_map[severity_lower]

    # Try partial match (e.g., "CRITICAL" contains "critical")
    for key, priority in severity_map.items():
        if key in severity_lower or severity_lower in key:
            return priority

    return default

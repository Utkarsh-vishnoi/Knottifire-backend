"""
Webhook payload adapters for transforming various source formats
into the canonical notification schema.
"""

from app.adapters.base import BaseAdapter, TransformationResult, AdapterMetadata
from app.adapters.registry import AdapterRegistry, get_global_registry

__all__ = [
    "BaseAdapter",
    "TransformationResult",
    "AdapterMetadata",
    "AdapterRegistry",
    "get_global_registry",
]

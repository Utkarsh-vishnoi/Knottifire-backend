"""
Adapter registry for managing and selecting webhook adapters.
"""

from typing import Dict, List, Optional, Any
from app.adapters.base import BaseAdapter, TransformationResult
from app.core.logging import get_logger


logger = get_logger("adapters.registry")


class AdapterRegistry:
    """
    Factory for selecting and using webhook payload adapters.

    Supports both explicit adapter selection (by source type) and
    automatic detection based on payload structure.
    """

    def __init__(self):
        self._adapters: Dict[str, BaseAdapter] = {}
        self._detection_order: List[str] = []

    def register(self, adapter: BaseAdapter, detection_priority: int = 50) -> None:
        """
        Register an adapter instance.

        Args:
            adapter: Adapter instance to register
            detection_priority: Priority for auto-detection (lower = checked first)
                                Default: 50, Native: 10, Generic: 100
        """
        source_type = adapter.SOURCE_TYPE
        self._adapters[source_type] = adapter

        # Insert in detection order based on priority
        inserted = False
        for i, existing_source in enumerate(self._detection_order):
            existing_adapter = self._adapters[existing_source]
            existing_priority = getattr(existing_adapter, 'DETECTION_PRIORITY', 50)
            if detection_priority < existing_priority:
                self._detection_order.insert(i, source_type)
                inserted = True
                break

        if not inserted:
            self._detection_order.append(source_type)

        logger.info(f"Registered adapter: {source_type} (priority: {detection_priority})")

    def get_adapter(self, source_type: str) -> BaseAdapter:
        """
        Get adapter by explicit source type.

        Args:
            source_type: Source identifier (e.g., "prometheus")

        Returns:
            Adapter instance

        Raises:
            KeyError: If source_type not registered
        """
        if source_type not in self._adapters:
            available = ', '.join(self._adapters.keys())
            raise KeyError(
                f"No adapter registered for source_type '{source_type}'. "
                f"Available: {available}"
            )

        return self._adapters[source_type]

    def detect_adapter(self, raw_payload: Dict[str, Any]) -> Optional[BaseAdapter]:
        """
        Auto-detect appropriate adapter for payload.

        Tries adapters in detection_order (by priority).

        Args:
            raw_payload: Raw webhook JSON

        Returns:
            First adapter that can handle the payload, or None
        """
        for source_type in self._detection_order:
            adapter = self._adapters[source_type]
            try:
                if adapter.can_handle(raw_payload):
                    logger.info(f"Auto-detected source type: {source_type}")
                    return adapter
            except Exception as e:
                logger.warning(f"Error checking {source_type} adapter: {e}")
                continue

        logger.warning("No adapter could handle payload")
        return None

    def transform(
        self,
        raw_payload: Dict[str, Any],
        source_type: Optional[str] = None,
        detected: bool = False
    ) -> List[TransformationResult]:
        """
        Transform payload using appropriate adapter.

        Args:
            raw_payload: Raw webhook JSON
            source_type: Explicit source type (optional, triggers auto-detect if None)
            detected: Whether source was auto-detected (internal use)

        Returns:
            List of TransformationResult (may contain multiple for batch adapters)

        Raises:
            KeyError: If explicit source_type not found
            ValueError: If no adapter can handle payload (auto-detect only)
        """
        if source_type:
            # Explicit source type
            adapter = self.get_adapter(source_type)
            detected = False
        else:
            # Auto-detect
            adapter = self.detect_adapter(raw_payload)
            if adapter is None:
                raise ValueError(
                    "Could not detect webhook source type. "
                    "Try using an explicit endpoint like /webhook/prometheus"
                )
            detected = True

        # Transform
        results = adapter.transform(raw_payload)

        # Mark as detected if auto-detected
        if detected:
            for result in results:
                result.metadata.detected = True

        return results

    def list_adapters(self) -> List[str]:
        """
        List all registered adapter source types.

        Returns:
            List of source type identifiers
        """
        return list(self._adapters.keys())


# Global registry instance
_global_registry: Optional[AdapterRegistry] = None


def get_global_registry() -> AdapterRegistry:
    """
    Get or create the global adapter registry.

    Lazy initialization with default adapters.

    Returns:
        Global AdapterRegistry instance
    """
    global _global_registry

    if _global_registry is None:
        _global_registry = AdapterRegistry()
        _initialize_default_adapters(_global_registry)

    return _global_registry


def _initialize_default_adapters(registry: AdapterRegistry) -> None:
    """
    Initialize registry with default adapters.

    Detection order (by priority):
    1. Native (priority 10) - exact match, fastest
    2. OCI (priority 20) - specific markers
    3. Prometheus (priority 30) - specific markers
    4. Grafana (priority 40) - specific markers
    5. Generic (priority 100) - fallback, always matches

    Args:
        registry: AdapterRegistry to populate
    """
    # Import adapters here to avoid circular imports
    from app.adapters.native import NativeAdapter
    from app.adapters.generic import GenericAdapter

    # Register native adapter (highest priority)
    native = NativeAdapter()
    native.DETECTION_PRIORITY = 10
    registry.register(native, detection_priority=10)

    # Register generic adapter (lowest priority, fallback)
    generic = GenericAdapter()
    generic.DETECTION_PRIORITY = 100
    registry.register(generic, detection_priority=100)

    # Source-specific adapters will be registered when created
    # (imported in main.py or dynamically)
    try:
        from app.adapters.oci import OCIAdapter
        oci = OCIAdapter()
        oci.DETECTION_PRIORITY = 20
        registry.register(oci, detection_priority=20)
    except ImportError:
        logger.debug("OCI adapter not available")

    try:
        from app.adapters.prometheus import PrometheusAdapter
        prometheus = PrometheusAdapter()
        prometheus.DETECTION_PRIORITY = 30
        registry.register(prometheus, detection_priority=30)
    except ImportError:
        logger.debug("Prometheus adapter not available")

    try:
        from app.adapters.grafana import GrafanaAdapter
        grafana = GrafanaAdapter()
        grafana.DETECTION_PRIORITY = 40
        registry.register(grafana, detection_priority=40)
    except ImportError:
        logger.debug("Grafana adapter not available")

    logger.info(f"Initialized adapter registry with {len(registry.list_adapters())} adapters")

"""Circuit breaker pattern for connector health checks.

Implements the circuit breaker state machine:
  CLOSED → (3 consecutive failures) → OPEN → (60s timeout) → HALF_OPEN → (success) → CLOSED
                                                                          (failure) → OPEN

Each connector has its own circuit breaker state tracked in memory.
For distributed deployments, this could be backed by Redis.
"""

import logging
import time
from enum import Enum
from threading import Lock

logger = logging.getLogger(__name__)

# Circuit breaker configuration
FAILURE_THRESHOLD = 3
RECOVERY_TIMEOUT_SECONDS = 60


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerEntry:
    """State tracking for a single circuit breaker."""

    def __init__(self):
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.last_success_time: float = 0.0

    def to_dict(self) -> dict:
        """Serialize state for API responses."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time if self.last_failure_time else None,
            "last_success_time": self.last_success_time if self.last_success_time else None,
        }


class CircuitBreakerRegistry:
    """Registry managing per-connector circuit breaker states.

    Thread-safe registry for tracking circuit breaker state across connectors.
    """

    def __init__(
        self,
        failure_threshold: int = FAILURE_THRESHOLD,
        recovery_timeout: int = RECOVERY_TIMEOUT_SECONDS,
    ):
        self._breakers: dict[str, CircuitBreakerEntry] = {}
        self._lock = Lock()
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

    def _get_entry(self, connector_id: str) -> CircuitBreakerEntry:
        """Get or create a circuit breaker entry for a connector."""
        if connector_id not in self._breakers:
            self._breakers[connector_id] = CircuitBreakerEntry()
        return self._breakers[connector_id]

    def get_state(self, connector_id: str) -> CircuitState:
        """Get the current circuit breaker state for a connector.

        Handles the OPEN → HALF_OPEN transition when recovery timeout expires.

        Args:
            connector_id: UUID string of the connector.

        Returns:
            Current CircuitState.
        """
        with self._lock:
            entry = self._get_entry(connector_id)

            if entry.state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                elapsed = time.time() - entry.last_failure_time
                if elapsed >= self.recovery_timeout:
                    entry.state = CircuitState.HALF_OPEN
                    logger.info(
                        "Circuit breaker for connector %s transitioned OPEN → HALF_OPEN "
                        "(recovery timeout elapsed: %.1fs)",
                        connector_id,
                        elapsed,
                    )

            return entry.state

    def record_success(self, connector_id: str) -> None:
        """Record a successful health check.

        Transitions:
          - HALF_OPEN → CLOSED (reset failure count)
          - CLOSED → stays CLOSED (reset failure count)

        Args:
            connector_id: UUID string of the connector.
        """
        with self._lock:
            entry = self._get_entry(connector_id)
            entry.failure_count = 0
            entry.last_success_time = time.time()

            if entry.state == CircuitState.HALF_OPEN:
                entry.state = CircuitState.CLOSED
                logger.info(
                    "Circuit breaker for connector %s transitioned HALF_OPEN → CLOSED",
                    connector_id,
                )
            elif entry.state == CircuitState.OPEN:
                # Shouldn't happen normally, but handle gracefully
                entry.state = CircuitState.CLOSED
            else:
                entry.state = CircuitState.CLOSED

    def record_failure(self, connector_id: str) -> None:
        """Record a failed health check.

        Transitions:
          - CLOSED: increment failure count; if threshold reached → OPEN
          - HALF_OPEN → OPEN (immediate trip)
          - OPEN → stays OPEN (update failure time)

        Args:
            connector_id: UUID string of the connector.
        """
        with self._lock:
            entry = self._get_entry(connector_id)
            entry.failure_count += 1
            entry.last_failure_time = time.time()

            if entry.state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN trips the breaker again
                entry.state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker for connector %s transitioned HALF_OPEN → OPEN "
                    "(failure in half-open state)",
                    connector_id,
                )
            elif entry.state == CircuitState.CLOSED:
                if entry.failure_count >= self.failure_threshold:
                    entry.state = CircuitState.OPEN
                    logger.warning(
                        "Circuit breaker for connector %s transitioned CLOSED → OPEN "
                        "(threshold reached: %d failures)",
                        connector_id,
                        entry.failure_count,
                    )

    def is_call_allowed(self, connector_id: str) -> bool:
        """Check if a health check call is allowed by the circuit breaker.

        Args:
            connector_id: UUID string of the connector.

        Returns:
            True if the call should proceed (CLOSED or HALF_OPEN after timeout).
            False if the circuit is OPEN (caller should return cached failure).
        """
        state = self.get_state(connector_id)
        return state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def get_info(self, connector_id: str) -> dict:
        """Get full circuit breaker info for a connector.

        Args:
            connector_id: UUID string of the connector.

        Returns:
            Dictionary with state, failure_count, and timestamps.
        """
        with self._lock:
            entry = self._get_entry(connector_id)
            # Update state in case OPEN → HALF_OPEN transition is pending
        # Call get_state (outside lock) for transition check
        state = self.get_state(connector_id)
        with self._lock:
            entry = self._get_entry(connector_id)
            info = entry.to_dict()
            info["state"] = state.value  # Use the potentially-updated state
            return info

    def remove(self, connector_id: str) -> None:
        """Remove circuit breaker state for a deleted connector."""
        with self._lock:
            self._breakers.pop(connector_id, None)


# Global circuit breaker registry (singleton)
circuit_breaker_registry = CircuitBreakerRegistry()

"""Unit tests for circuit breaker pattern."""

import time
from unittest.mock import patch

import pytest

from backend.app.core.circuit_breaker import (
    CircuitBreakerEntry,
    CircuitBreakerRegistry,
    CircuitState,
    FAILURE_THRESHOLD,
    RECOVERY_TIMEOUT_SECONDS,
)


class TestCircuitBreakerEntry:
    """Tests for CircuitBreakerEntry data class."""

    def test_initial_state_is_closed(self):
        entry = CircuitBreakerEntry()
        assert entry.state == CircuitState.CLOSED
        assert entry.failure_count == 0
        assert entry.last_failure_time == 0.0

    def test_to_dict_serialization(self):
        entry = CircuitBreakerEntry()
        entry.state = CircuitState.OPEN
        entry.failure_count = 3
        entry.last_failure_time = 1000.0
        result = entry.to_dict()
        assert result["state"] == "open"
        assert result["failure_count"] == 3
        assert result["last_failure_time"] == 1000.0


class TestCircuitBreakerRegistry:
    """Tests for the circuit breaker registry state machine."""

    def test_new_connector_starts_closed(self):
        registry = CircuitBreakerRegistry()
        state = registry.get_state("connector-1")
        assert state == CircuitState.CLOSED

    def test_single_failure_stays_closed(self):
        registry = CircuitBreakerRegistry()
        registry.record_failure("connector-1")
        state = registry.get_state("connector-1")
        assert state == CircuitState.CLOSED

    def test_threshold_failures_opens_circuit(self):
        """3 consecutive failures should open the circuit."""
        registry = CircuitBreakerRegistry(failure_threshold=3)
        for _ in range(3):
            registry.record_failure("connector-1")
        state = registry.get_state("connector-1")
        assert state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        """Success after failures should reset counter and stay closed."""
        registry = CircuitBreakerRegistry(failure_threshold=3)
        registry.record_failure("connector-1")
        registry.record_failure("connector-1")
        registry.record_success("connector-1")
        # Two more failures shouldn't trip the breaker
        registry.record_failure("connector-1")
        registry.record_failure("connector-1")
        state = registry.get_state("connector-1")
        assert state == CircuitState.CLOSED

    def test_open_circuit_transitions_to_half_open_after_timeout(self):
        """After recovery timeout, OPEN → HALF_OPEN."""
        registry = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout=1)
        for _ in range(3):
            registry.record_failure("connector-1")
        assert registry.get_state("connector-1") == CircuitState.OPEN

        # Simulate time passing
        with patch("backend.app.core.circuit_breaker.time.time", return_value=time.time() + 2):
            state = registry.get_state("connector-1")
        assert state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        """Success in HALF_OPEN state should close the circuit."""
        registry = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout=0)
        for _ in range(3):
            registry.record_failure("connector-1")
        # Immediately transition to HALF_OPEN (recovery_timeout=0)
        registry.get_state("connector-1")  # triggers transition
        registry.record_success("connector-1")
        state = registry.get_state("connector-1")
        assert state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        """Failure in HALF_OPEN state should reopen the circuit."""
        registry = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            registry.record_failure("connector-1")
        assert registry.get_state("connector-1") == CircuitState.OPEN

        # Simulate recovery timeout elapsed → HALF_OPEN
        with patch("backend.app.core.circuit_breaker.time.time", return_value=time.time() + 61):
            state = registry.get_state("connector-1")
            assert state == CircuitState.HALF_OPEN
            # Now record a failure in HALF_OPEN
            registry.record_failure("connector-1")

        # Should be back to OPEN (and not transition to HALF_OPEN since timeout hasn't elapsed again)
        # Use the real time (which hasn't advanced 60s), so it stays OPEN
        state = registry.get_state("connector-1")
        assert state == CircuitState.OPEN

    def test_is_call_allowed_when_closed(self):
        registry = CircuitBreakerRegistry()
        assert registry.is_call_allowed("connector-1") is True

    def test_is_call_allowed_when_open(self):
        registry = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            registry.record_failure("connector-1")
        assert registry.is_call_allowed("connector-1") is False

    def test_is_call_allowed_when_half_open(self):
        registry = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout=0)
        for _ in range(3):
            registry.record_failure("connector-1")
        # Trigger transition to HALF_OPEN
        registry.get_state("connector-1")
        assert registry.is_call_allowed("connector-1") is True

    def test_independent_connectors(self):
        """Each connector has its own circuit breaker state."""
        registry = CircuitBreakerRegistry(failure_threshold=3)
        for _ in range(3):
            registry.record_failure("connector-1")
        assert registry.get_state("connector-1") == CircuitState.OPEN
        assert registry.get_state("connector-2") == CircuitState.CLOSED

    def test_remove_cleans_up_state(self):
        registry = CircuitBreakerRegistry()
        registry.record_failure("connector-1")
        registry.remove("connector-1")
        # After removal, it starts fresh
        state = registry.get_state("connector-1")
        assert state == CircuitState.CLOSED

    def test_get_info_returns_correct_data(self):
        registry = CircuitBreakerRegistry(failure_threshold=3)
        registry.record_failure("connector-1")
        registry.record_failure("connector-1")
        info = registry.get_info("connector-1")
        assert info["state"] == "closed"
        assert info["failure_count"] == 2
        assert info["last_failure_time"] is not None

    def test_default_threshold_is_three(self):
        """Verify the default failure threshold matches spec (3 failures)."""
        assert FAILURE_THRESHOLD == 3

    def test_default_recovery_timeout_is_sixty_seconds(self):
        """Verify the default recovery timeout matches spec (60 seconds)."""
        assert RECOVERY_TIMEOUT_SECONDS == 60

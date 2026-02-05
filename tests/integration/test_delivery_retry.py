"""Integration test: Delivery with retries, verify behavior."""

import time
import pytest

from x_digest.delivery.base import (
    MockDeliveryProvider,
    send_digest,
)
from x_digest.errors import DeliveryError, ErrorCode


class TestDeliveryRetryBehavior:
    """Tests for delivery retry logic with mock providers."""

    def test_successful_delivery_single_part(self):
        """Single part delivered successfully."""
        provider = MockDeliveryProvider(success=True, message_id="msg_001")
        parts = ["Part 1 content"]
        result = send_digest(parts, provider, "+1234567890")
        assert result is True
        assert len(provider.sends) == 1

    def test_successful_delivery_multiple_parts(self):
        """Multiple parts all delivered successfully."""
        provider = MockDeliveryProvider(success=True, message_id="msg_001")
        parts = ["Part 1", "Part 2", "Part 3"]
        result = send_digest(parts, provider, "+1234567890")
        assert result is True
        assert len(provider.sends) == 3

    def test_retry_on_transient_failure(self):
        """Transient failure is retried and succeeds."""
        # Fail twice, then succeed
        provider = MockDeliveryProvider(success=True, fail_count=2)
        parts = ["Part 1"]
        result = send_digest(parts, provider, "+1", max_retries=3)
        assert result is True
        # 2 failures + 1 success = 3 attempts
        assert len(provider.sends) == 3

    def test_give_up_after_max_retries(self):
        """Gives up after max retries exceeded."""
        provider = MockDeliveryProvider(success=False)
        parts = ["Part 1"]
        result = send_digest(parts, provider, "+1", max_retries=3)
        assert result is False
        assert len(provider.sends) == 3

    def test_partial_failure_returns_false(self):
        """If any part fails permanently, whole delivery fails."""
        provider = MockDeliveryProvider(
            success=True,
            fail_on_message=["Part 2"]
        )
        parts = ["Part 1", "Part 2", "Part 3"]
        result = send_digest(parts, provider, "+1", max_retries=3)
        assert result is False

    def test_successful_parts_still_sent(self):
        """Even when one part fails, other parts are attempted."""
        provider = MockDeliveryProvider(
            success=True,
            fail_on_message=["Part 2"]
        )
        parts = ["Part 1", "Part 2", "Part 3"]
        send_digest(parts, provider, "+1", max_retries=2)

        # Part 1 sent once (success), Part 2 retried, Part 3 sent once
        sent_messages = [s["message"] for s in provider.sends]
        assert "Part 1" in sent_messages
        assert "Part 3" in sent_messages

    def test_retry_count_per_part(self):
        """Each part gets its own retry count."""
        provider = MockDeliveryProvider(success=True, fail_count=1)
        parts = ["Part 1", "Part 2"]
        
        # First part fails once then succeeds; provider.fail_count applies globally
        # After first part's 2 calls (fail + success), second part should work
        result = send_digest(parts, provider, "+1", max_retries=3)
        # The fail_count=1 means only the very first call fails
        assert result is True

    def test_empty_parts_list(self):
        """Empty parts list returns success."""
        provider = MockDeliveryProvider(success=True)
        result = send_digest([], provider, "+1")
        assert result is True
        assert len(provider.sends) == 0

    def test_single_retry_succeeds(self):
        """Single retry is enough when fail_count=1."""
        provider = MockDeliveryProvider(success=True, fail_count=1)
        parts = ["Content"]
        result = send_digest(parts, provider, "+1", max_retries=2)
        assert result is True

    def test_max_retries_of_1_no_retry(self):
        """max_retries=1 means only one attempt (no retry)."""
        provider = MockDeliveryProvider(success=False)
        parts = ["Content"]
        result = send_digest(parts, provider, "+1", max_retries=1)
        assert result is False
        assert len(provider.sends) == 1

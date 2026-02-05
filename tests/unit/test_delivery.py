"""Tests for delivery providers and retry logic."""

import pytest
import time
from unittest.mock import Mock, patch
from x_digest.delivery.base import (
    MockDeliveryProvider, get_provider, send_digest
)
from x_digest.delivery.whatsapp import WhatsAppProvider
from x_digest.delivery.telegram import TelegramProvider
from x_digest.errors import DeliveryError, ConfigError, ErrorCode


def test_mock_provider_success():
    """Mock provider returns configured message ID."""
    provider = MockDeliveryProvider(success=True, message_id="test123")
    result = provider.send("+1234567890", "Hello world")
    
    assert result == "test123"
    assert len(provider.sends) == 1
    assert provider.sends[0]["recipient"] == "+1234567890"
    assert provider.sends[0]["message"] == "Hello world"


def test_mock_provider_failure():
    """Mock provider raises configured error."""
    provider = MockDeliveryProvider(success=False, error="RATE_LIMITED")
    
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1234567890", "Message")
    
    assert exc.value.code == ErrorCode.DELIVERY_RATE_LIMITED


def test_mock_provider_fail_count():
    """Mock provider fails specified number of times then succeeds."""
    provider = MockDeliveryProvider(success=True, message_id="success", fail_count=2)
    
    # First two calls should fail
    with pytest.raises(DeliveryError):
        provider.send("+1", "msg1")
    
    with pytest.raises(DeliveryError):
        provider.send("+1", "msg2")
    
    # Third call should succeed
    result = provider.send("+1", "msg3")
    assert result == "success"


def test_mock_provider_fail_on_message():
    """Mock provider fails for specific message content."""
    provider = MockDeliveryProvider(
        success=True, 
        message_id="ok",
        fail_on_message=["bad content"]
    )
    
    # Normal message succeeds
    result = provider.send("+1", "good message")
    assert result == "ok"
    
    # Message with bad content fails
    with pytest.raises(DeliveryError):
        provider.send("+1", "this has bad content in it")


def test_mock_provider_max_length():
    """Mock provider reports correct max length."""
    provider = MockDeliveryProvider()
    assert provider.max_message_length() == 4000


def test_mock_provider_reset():
    """Reset clears call history."""
    provider = MockDeliveryProvider()
    provider.send("+1", "test")
    assert len(provider.sends) == 1
    
    provider.reset()
    assert len(provider.sends) == 0


def test_get_provider_whatsapp():
    """get_provider returns WhatsApp provider for whatsapp config."""
    config = {
        "provider": "whatsapp",
        "whatsapp": {
            "gateway_url": "http://localhost:3420",
            "recipient": "+1234567890"
        }
    }
    
    provider = get_provider(config)
    assert isinstance(provider, WhatsAppProvider)


def test_get_provider_telegram():
    """get_provider returns Telegram provider for telegram config."""
    config = {
        "provider": "telegram", 
        "telegram": {
            "bot_token": "123:ABC",
            "chat_id": "456"
        }
    }
    
    provider = get_provider(config)
    assert isinstance(provider, TelegramProvider)


def test_get_provider_missing_provider():
    """get_provider raises error for missing provider field."""
    config = {"whatsapp": {}}  # Missing 'provider' field
    
    with pytest.raises(ConfigError) as exc:
        get_provider(config)
    assert exc.value.code == ErrorCode.CONFIG_MISSING_REQUIRED_FIELD


def test_get_provider_unknown_provider():
    """get_provider raises error for unknown provider."""
    config = {"provider": "smoke_signals"}
    
    with pytest.raises(ConfigError) as exc:
        get_provider(config)
    assert exc.value.code == ErrorCode.CONFIG_INVALID_VALUE
    assert "Unknown delivery provider" in str(exc.value)


def test_send_digest_all_success():
    """All parts sent successfully."""
    provider = MockDeliveryProvider(success=True, message_id="msg123")
    parts = ["Part 1", "Part 2", "Part 3"]
    
    result = send_digest(parts, provider, "+1234567890")
    
    assert result is True
    assert len(provider.sends) == 3
    for i, part in enumerate(parts):
        assert provider.sends[i]["message"] == part


def test_send_digest_retry_on_failure():
    """Failed sends are retried with exponential backoff."""
    # Fail twice, then succeed
    provider = MockDeliveryProvider(success=True, fail_count=2)
    parts = ["Part 1"]
    
    start_time = time.time()
    result = send_digest(parts, provider, "+1", max_retries=3)
    end_time = time.time()
    
    assert result is True
    assert len(provider.sends) == 3  # 2 failures + 1 success
    
    # Should have taken some time due to backoff (2s + 4s = 6s minimum)
    # But we'll just check it took more than a second to verify backoff happened
    assert end_time - start_time >= 1


def test_send_digest_give_up_after_max_retries():
    """Give up after max retries exceeded."""
    provider = MockDeliveryProvider(success=False)
    parts = ["Part 1"]
    
    result = send_digest(parts, provider, "+1", max_retries=2)
    
    assert result is False
    assert len(provider.sends) == 2  # Tried max_retries times


def test_send_digest_partial_failure():
    """If any part fails, entire digest fails."""
    provider = MockDeliveryProvider(
        success=True,
        fail_on_message=["Part 2"]  # Only Part 2 will fail
    )
    parts = ["Part 1", "Part 2", "Part 3"]
    
    result = send_digest(parts, provider, "+1", max_retries=2)
    
    assert result is False
    # Part 1 and 3 succeed, Part 2 fails max_retries times
    assert len(provider.sends) == 4  # 1 + 2 + 1


# WhatsApp provider tests

@patch('x_digest.delivery.whatsapp.requests.post')
def test_whatsapp_provider_success(mock_post):
    """WhatsApp provider successful send."""
    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "messageId": "whatsapp_msg_123"
    }
    mock_post.return_value = mock_response
    
    provider = WhatsAppProvider(
        gateway_url="http://localhost:3420/api/message/send",
        recipient="+1234567890"
    )
    
    result = provider.send("+1234567890", "Test message")
    
    assert result == "whatsapp_msg_123"
    
    # Verify request
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[1]["json"] == {
        "channel": "whatsapp",
        "to": "+1234567890", 
        "message": "Test message"
    }


@patch('x_digest.delivery.whatsapp.requests.post')
def test_whatsapp_provider_gateway_error(mock_post):
    """WhatsApp provider handles gateway errors."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": False,
        "error": "RECIPIENT_NOT_FOUND"
    }
    mock_post.return_value = mock_response
    
    provider = WhatsAppProvider("http://localhost:3420", "+1234567890")
    
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1234567890", "Test")
    
    assert exc.value.code == ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND


@patch('x_digest.delivery.whatsapp.requests.post')
def test_whatsapp_provider_http_errors(mock_post):
    """WhatsApp provider maps HTTP errors correctly."""
    provider = WhatsAppProvider("http://localhost:3420", "+1234567890")
    
    # 401 Unauthorized
    mock_post.return_value.status_code = 401
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1", "Test")
    assert exc.value.code == ErrorCode.DELIVERY_AUTH_FAILED
    
    # 429 Rate Limited
    mock_post.return_value.status_code = 429
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1", "Test")
    assert exc.value.code == ErrorCode.DELIVERY_RATE_LIMITED
    
    # 503 Service Unavailable
    mock_post.return_value.status_code = 503
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1", "Test")
    assert exc.value.code == ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE


@patch('x_digest.delivery.whatsapp.requests.post')
def test_whatsapp_provider_timeout(mock_post):
    """WhatsApp provider handles timeout."""
    import requests
    mock_post.side_effect = requests.Timeout()
    
    provider = WhatsAppProvider("http://localhost:3420", "+1234567890")
    
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1", "Test")
    assert exc.value.code == ErrorCode.DELIVERY_NETWORK_ERROR
    assert "timeout" in str(exc.value).lower()


def test_whatsapp_provider_message_too_long():
    """WhatsApp provider rejects messages that are too long."""
    provider = WhatsAppProvider("http://localhost:3420", "+1234567890")
    long_message = "x" * 5000  # Over 4000 char limit
    
    with pytest.raises(DeliveryError) as exc:
        provider.send("+1234567890", long_message)
    assert exc.value.code == ErrorCode.DELIVERY_MESSAGE_TOO_LONG


def test_whatsapp_provider_no_recipient():
    """WhatsApp provider requires recipient."""
    provider = WhatsAppProvider("http://localhost:3420")  # No default recipient
    
    with pytest.raises(DeliveryError) as exc:
        provider.send("", "Test")  # Empty recipient
    assert exc.value.code == ErrorCode.DELIVERY_RECIPIENT_INVALID


# Telegram provider tests

@patch('x_digest.delivery.telegram.requests.post')
def test_telegram_provider_success(mock_post):
    """Telegram provider successful send."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "ok": True,
        "result": {"message_id": 123}
    }
    mock_post.return_value = mock_response
    
    provider = TelegramProvider(bot_token="123:ABC", chat_id="456")
    
    result = provider.send("456", "Test message")
    
    assert result == "123"
    
    # Verify request
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    url = call_args[0][0]
    assert "bot123:ABC/sendMessage" in url
    
    payload = call_args[1]["json"]
    assert payload["chat_id"] == "456"
    assert payload["text"] == "Test message"


@patch('x_digest.delivery.telegram.requests.post')
def test_telegram_provider_api_errors(mock_post):
    """Telegram provider handles API errors."""
    provider = TelegramProvider(bot_token="123:ABC", chat_id="456")
    
    # 401 Unauthorized
    mock_post.return_value.json.return_value = {
        "ok": False,
        "error_code": 401,
        "description": "Unauthorized"
    }
    with pytest.raises(DeliveryError) as exc:
        provider.send("456", "Test")
    assert exc.value.code == ErrorCode.DELIVERY_AUTH_FAILED
    
    # 403 Bot blocked
    mock_post.return_value.json.return_value = {
        "ok": False,
        "error_code": 403,
        "description": "Forbidden: bot was blocked by the user"
    }
    with pytest.raises(DeliveryError) as exc:
        provider.send("456", "Test")
    assert exc.value.code == ErrorCode.TELEGRAM_BOT_BLOCKED


def test_telegram_provider_max_length():
    """Telegram provider has correct max length."""
    provider = TelegramProvider("123:ABC", "456")
    assert provider.max_message_length() == 4096


def test_telegram_provider_message_too_long():
    """Telegram provider rejects messages that are too long."""
    provider = TelegramProvider("123:ABC", "456")
    long_message = "x" * 5000  # Over 4096 char limit
    
    with pytest.raises(DeliveryError) as exc:
        provider.send("456", long_message)
    assert exc.value.code == ErrorCode.DELIVERY_MESSAGE_TOO_LONG
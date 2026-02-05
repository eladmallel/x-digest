"""Tests for error codes and custom exceptions."""

import pytest
from x_digest.errors import (
    ErrorCode, ERROR_DESCRIPTIONS,
    XDigestError, BirdError, LLMError, DeliveryError, ConfigError
)


def test_error_codes_are_strings():
    """All error codes are valid enum members with string values."""
    assert ErrorCode.BIRD_AUTH_FAILED.value == "BIRD_AUTH_FAILED"
    assert ErrorCode.LLM_TIMEOUT.value == "LLM_TIMEOUT"
    assert ErrorCode.DELIVERY_SEND_FAILED.value == "DELIVERY_SEND_FAILED"
    assert ErrorCode.CONFIG_FILE_NOT_FOUND.value == "CONFIG_FILE_NOT_FOUND"


def test_bird_error_carries_code():
    """BirdError carries the error code and message."""
    err = BirdError(ErrorCode.BIRD_AUTH_FAILED)
    assert err.code == ErrorCode.BIRD_AUTH_FAILED
    assert "Twitter authentication failed" in str(err)


def test_llm_error_carries_code():
    """LLMError carries the error code and message."""
    err = LLMError(ErrorCode.LLM_TIMEOUT)
    assert err.code == ErrorCode.LLM_TIMEOUT
    assert "timeout" in str(err).lower()


def test_delivery_error_carries_code():
    """DeliveryError carries the error code and message."""
    err = DeliveryError(ErrorCode.DELIVERY_SEND_FAILED)
    assert err.code == ErrorCode.DELIVERY_SEND_FAILED
    assert "send" in str(err).lower()


def test_config_error_carries_code():
    """ConfigError carries the error code and message."""
    err = ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)
    assert err.code == ErrorCode.CONFIG_FILE_NOT_FOUND
    assert "not found" in str(err).lower()


def test_all_codes_have_description():
    """Every error code has a description in ERROR_DESCRIPTIONS."""
    for code in ErrorCode:
        assert code in ERROR_DESCRIPTIONS
        assert isinstance(ERROR_DESCRIPTIONS[code], str)
        assert len(ERROR_DESCRIPTIONS[code]) > 0


def test_custom_error_message():
    """Errors can have custom messages."""
    custom_msg = "Custom error message"
    err = BirdError(ErrorCode.BIRD_AUTH_FAILED, custom_msg)
    assert err.message == custom_msg
    assert custom_msg in str(err)


def test_error_inheritance():
    """All custom errors inherit from XDigestError."""
    assert issubclass(BirdError, XDigestError)
    assert issubclass(LLMError, XDigestError)
    assert issubclass(DeliveryError, XDigestError)
    assert issubclass(ConfigError, XDigestError)
    
    # And XDigestError inherits from Exception
    assert issubclass(XDigestError, Exception)
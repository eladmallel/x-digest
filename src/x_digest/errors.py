"""
Error codes and custom exceptions for x-digest.

Defines a comprehensive error code system that enables structured error handling
without exposing untrusted content to the monitoring system.

All exceptions carry predefined error codes from the ErrorCode enum to ensure
consistent error reporting and enable automated alerting based on error types.
"""

from enum import Enum
from typing import Optional


class ErrorCode(Enum):
    """Predefined error codes for structured error handling."""
    
    # Configuration errors
    CONFIG_FILE_NOT_FOUND = "CONFIG_FILE_NOT_FOUND"
    CONFIG_INVALID_JSON = "CONFIG_INVALID_JSON" 
    CONFIG_VERSION_MISMATCH = "CONFIG_VERSION_MISMATCH"
    CONFIG_MISSING_REQUIRED_FIELD = "CONFIG_MISSING_REQUIRED_FIELD"
    CONFIG_INVALID_VALUE = "CONFIG_INVALID_VALUE"
    
    # Twitter/bird CLI errors
    BIRD_AUTH_FAILED = "BIRD_AUTH_FAILED"
    BIRD_RATE_LIMITED = "BIRD_RATE_LIMITED"
    BIRD_NETWORK_ERROR = "BIRD_NETWORK_ERROR"
    BIRD_INVALID_LIST_ID = "BIRD_INVALID_LIST_ID"
    BIRD_COMMAND_FAILED = "BIRD_COMMAND_FAILED"
    BIRD_JSON_PARSE_ERROR = "BIRD_JSON_PARSE_ERROR"
    
    # LLM API errors
    LLM_API_AUTH = "LLM_API_AUTH"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_EMPTY_RESPONSE = "LLM_EMPTY_RESPONSE"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    LLM_QUOTA_EXCEEDED = "LLM_QUOTA_EXCEEDED"
    
    # Image processing errors
    IMAGE_DOWNLOAD_FAILED = "IMAGE_DOWNLOAD_FAILED"
    IMAGE_ENCODING_FAILED = "IMAGE_ENCODING_FAILED"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    IMAGE_INVALID_FORMAT = "IMAGE_INVALID_FORMAT"
    
    # Delivery errors
    DELIVERY_AUTH_FAILED = "DELIVERY_AUTH_FAILED"
    DELIVERY_SEND_FAILED = "DELIVERY_SEND_FAILED"
    DELIVERY_RATE_LIMITED = "DELIVERY_RATE_LIMITED"
    DELIVERY_MESSAGE_TOO_LONG = "DELIVERY_MESSAGE_TOO_LONG"
    DELIVERY_RECIPIENT_INVALID = "DELIVERY_RECIPIENT_INVALID"
    DELIVERY_NETWORK_ERROR = "DELIVERY_NETWORK_ERROR"
    
    # WhatsApp specific
    WHATSAPP_GATEWAY_UNAVAILABLE = "WHATSAPP_GATEWAY_UNAVAILABLE"
    WHATSAPP_SESSION_EXPIRED = "WHATSAPP_SESSION_EXPIRED"
    WHATSAPP_RECIPIENT_NOT_FOUND = "WHATSAPP_RECIPIENT_NOT_FOUND"
    
    # Telegram specific
    TELEGRAM_BOT_BLOCKED = "TELEGRAM_BOT_BLOCKED"
    TELEGRAM_CHAT_NOT_FOUND = "TELEGRAM_CHAT_NOT_FOUND"
    
    # File system errors
    STATUS_FILE_LOCKED = "STATUS_FILE_LOCKED"
    STATUS_FILE_CORRUPT = "STATUS_FILE_CORRUPT"
    WRITE_PERMISSION_DENIED = "WRITE_PERMISSION_DENIED"
    
    # Generic/system errors
    SCRIPT_EXCEPTION = "SCRIPT_EXCEPTION"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    ENVIRONMENT_INVALID = "ENVIRONMENT_INVALID"


# Human-readable descriptions for error codes
ERROR_DESCRIPTIONS = {
    # Configuration
    ErrorCode.CONFIG_FILE_NOT_FOUND: "Configuration file not found in search paths",
    ErrorCode.CONFIG_INVALID_JSON: "Configuration file contains invalid JSON",
    ErrorCode.CONFIG_VERSION_MISMATCH: "Configuration version not supported",
    ErrorCode.CONFIG_MISSING_REQUIRED_FIELD: "Required configuration field missing",
    ErrorCode.CONFIG_INVALID_VALUE: "Configuration field has invalid value",
    
    # Bird/Twitter
    ErrorCode.BIRD_AUTH_FAILED: "Twitter authentication failed (cookies expired)",
    ErrorCode.BIRD_RATE_LIMITED: "Twitter rate limit exceeded",
    ErrorCode.BIRD_NETWORK_ERROR: "Network error fetching tweets",
    ErrorCode.BIRD_INVALID_LIST_ID: "Twitter list ID not found or not accessible",
    ErrorCode.BIRD_COMMAND_FAILED: "bird CLI command failed",
    ErrorCode.BIRD_JSON_PARSE_ERROR: "Failed to parse bird CLI output",
    
    # LLM
    ErrorCode.LLM_API_AUTH: "LLM API authentication failed",
    ErrorCode.LLM_RATE_LIMITED: "LLM API rate limit exceeded",
    ErrorCode.LLM_TIMEOUT: "LLM API request timed out",
    ErrorCode.LLM_EMPTY_RESPONSE: "LLM returned empty response",
    ErrorCode.LLM_INVALID_RESPONSE: "LLM response format invalid",
    ErrorCode.LLM_QUOTA_EXCEEDED: "LLM API quota exceeded",
    
    # Images
    ErrorCode.IMAGE_DOWNLOAD_FAILED: "Failed to download image(s)",
    ErrorCode.IMAGE_ENCODING_FAILED: "Failed to encode image for LLM",
    ErrorCode.IMAGE_TOO_LARGE: "Image file too large",
    ErrorCode.IMAGE_INVALID_FORMAT: "Unsupported image format",
    
    # Delivery
    ErrorCode.DELIVERY_AUTH_FAILED: "Message delivery authentication failed",
    ErrorCode.DELIVERY_SEND_FAILED: "Failed to send message",
    ErrorCode.DELIVERY_RATE_LIMITED: "Message delivery rate limited",
    ErrorCode.DELIVERY_MESSAGE_TOO_LONG: "Message exceeds length limit",
    ErrorCode.DELIVERY_RECIPIENT_INVALID: "Invalid recipient identifier",
    ErrorCode.DELIVERY_NETWORK_ERROR: "Network error during delivery",
    
    # WhatsApp
    ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE: "WhatsApp gateway service unavailable",
    ErrorCode.WHATSAPP_SESSION_EXPIRED: "WhatsApp session expired (re-link needed)",
    ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND: "Phone number not on WhatsApp",
    
    # Telegram
    ErrorCode.TELEGRAM_BOT_BLOCKED: "Bot blocked by user",
    ErrorCode.TELEGRAM_CHAT_NOT_FOUND: "Telegram chat not found",
    
    # File system
    ErrorCode.STATUS_FILE_LOCKED: "Status file locked by another process",
    ErrorCode.STATUS_FILE_CORRUPT: "Status file corrupted",
    ErrorCode.WRITE_PERMISSION_DENIED: "Permission denied writing to file",
    
    # System
    ErrorCode.SCRIPT_EXCEPTION: "Unhandled exception in script",
    ErrorCode.DEPENDENCY_MISSING: "Required dependency missing",
    ErrorCode.ENVIRONMENT_INVALID: "Invalid environment configuration",
}


class XDigestError(Exception):
    """Base exception class for all x-digest errors."""
    
    def __init__(self, code: ErrorCode, message: Optional[str] = None):
        self.code = code
        self.message = message or ERROR_DESCRIPTIONS.get(code, str(code.value))
        super().__init__(self.message)
    
    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


class ConfigError(XDigestError):
    """Configuration file or validation errors."""
    pass


class BirdError(XDigestError):
    """Bird CLI or Twitter API errors."""
    pass


class LLMError(XDigestError):
    """LLM provider API errors."""
    pass


class ImageError(XDigestError):
    """Image download or processing errors."""
    pass


class DeliveryError(XDigestError):
    """Message delivery errors."""
    pass


class StatusError(XDigestError):
    """Status file management errors."""
    pass
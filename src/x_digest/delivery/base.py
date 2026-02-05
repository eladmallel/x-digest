"""
Base delivery provider interface.

Defines the abstract interface for all message delivery providers and
provides utilities for provider registration and mock testing.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import time

from ..errors import DeliveryError, ConfigError, ErrorCode


class DeliveryProvider(ABC):
    """Base class for all message delivery providers."""
    
    @abstractmethod
    def send(self, recipient: str, message: str) -> str:
        """
        Send a message to a recipient.
        
        Args:
            recipient: Recipient identifier (phone number, chat ID, etc.)
            message: Message text to send
            
        Returns:
            Message ID from the provider
            
        Raises:
            DeliveryError: If sending fails
        """
        pass
    
    @abstractmethod
    def max_message_length(self) -> int:
        """
        Maximum characters per message for this provider.
        
        Returns:
            Maximum message length in characters
        """
        pass
    
    @property
    def name(self) -> str:
        """Provider name for logging."""
        return self.__class__.__name__


class MockDeliveryProvider(DeliveryProvider):
    """
    Mock delivery provider for testing.
    
    Simulates message sending with configurable success/failure behavior.
    """
    
    def __init__(self, success: bool = True, message_id: str = "mock_msg_123", error: Optional[str] = None, fail_count: int = 0, fail_on_message: Optional[List[str]] = None):
        """
        Initialize mock provider.
        
        Args:
            success: Whether sends should succeed
            message_id: Message ID to return on success
            error: Error code to raise on failure
            fail_count: Number of times to fail before succeeding
            fail_on_message: List of message texts that should always fail
        """
        self.success = success
        self.message_id = message_id
        self.error = error
        self.fail_count = fail_count
        self.fail_on_message = fail_on_message or []
        
        self.sends: List[Dict[str, Any]] = []
        self._call_count = 0
    
    def send(self, recipient: str, message: str) -> str:
        """Mock send implementation."""
        self.sends.append({
            "recipient": recipient,
            "message": message,
            "timestamp": time.time()
        })
        
        self._call_count += 1
        
        # Check for specific message failures
        if any(fail_msg in message for fail_msg in self.fail_on_message):
            raise DeliveryError(ErrorCode.DELIVERY_SEND_FAILED, "Configured to fail")
        
        # Check fail count
        if self._call_count <= self.fail_count:
            raise DeliveryError(ErrorCode.DELIVERY_SEND_FAILED, "Configured failure count")
        
        # Check general success flag
        if not self.success:
            error_code = ErrorCode.DELIVERY_SEND_FAILED
            if self.error:
                # Map string errors to error codes
                error_map = {
                    "RATE_LIMITED": ErrorCode.DELIVERY_RATE_LIMITED,
                    "AUTH_FAILED": ErrorCode.DELIVERY_AUTH_FAILED,
                    "RECIPIENT_INVALID": ErrorCode.DELIVERY_RECIPIENT_INVALID
                }
                error_code = error_map.get(self.error, ErrorCode.DELIVERY_SEND_FAILED)
            
            raise DeliveryError(error_code)
        
        return self.message_id
    
    def max_message_length(self) -> int:
        """Mock max length."""
        return 4000
    
    def reset(self):
        """Reset call tracking."""
        self.sends = []
        self._call_count = 0


def get_provider(config: Dict[str, Any]) -> DeliveryProvider:
    """
    Get delivery provider instance from configuration.
    
    Args:
        config: Delivery configuration dictionary
        
    Returns:
        Configured delivery provider instance
        
    Raises:
        ConfigError: If provider not found or misconfigured
    """
    provider_type = config.get("provider")
    
    if not provider_type:
        raise ConfigError(ErrorCode.CONFIG_MISSING_REQUIRED_FIELD, "delivery.provider required")
    
    if provider_type == "whatsapp":
        from .whatsapp import WhatsAppProvider
        whatsapp_config = config.get("whatsapp", {})
        return WhatsAppProvider(
            cli_path=whatsapp_config.get("cli_path"),
            node_path=whatsapp_config.get("node_path"),
            recipient=whatsapp_config.get("recipient"),
            timeout=whatsapp_config.get("timeout", 30),
        )
    
    elif provider_type == "telegram":
        from .telegram import TelegramProvider
        telegram_config = config.get("telegram", {})
        return TelegramProvider(
            bot_token=telegram_config.get("bot_token"),
            chat_id=telegram_config.get("chat_id")
        )
    
    else:
        raise ConfigError(
            ErrorCode.CONFIG_INVALID_VALUE,
            f"Unknown delivery provider: {provider_type}"
        )


def send_digest(parts: List[str], provider: DeliveryProvider, recipient: str, max_retries: int = 3) -> bool:
    """
    Send digest parts with retry logic.
    
    Args:
        parts: List of message parts to send
        provider: Delivery provider instance
        recipient: Recipient identifier
        max_retries: Maximum retry attempts per part
        
    Returns:
        True if all parts sent successfully, False if any failed
        
    Behavior:
    - Retries each failed part up to max_retries times
    - Uses exponential backoff between retries
    - If ANY part fails after all retries, entire digest is considered failed
    """
    failed_parts = []
    
    for i, part in enumerate(parts):
        success = False
        
        for attempt in range(max_retries):
            try:
                provider.send(recipient, part)
                success = True
                break
            except DeliveryError:
                if attempt < max_retries - 1:
                    # Exponential backoff: 2, 4, 8 seconds
                    time.sleep(2 ** attempt)
        
        if not success:
            failed_parts.append(i)
    
    return len(failed_parts) == 0
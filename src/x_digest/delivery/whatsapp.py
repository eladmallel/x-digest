"""
WhatsApp delivery provider.

Sends messages via WhatsApp gateway HTTP API (e.g., OpenClaw, Baileys).
Supports the standard WhatsApp gateway contract with proper error mapping.
"""

import requests
from typing import Optional

from .base import DeliveryProvider
from ..errors import DeliveryError, ErrorCode


class WhatsAppProvider(DeliveryProvider):
    """WhatsApp message delivery provider."""
    
    def __init__(self, gateway_url: str, recipient: Optional[str] = None):
        """
        Initialize WhatsApp provider.
        
        Args:
            gateway_url: WhatsApp gateway endpoint URL
            recipient: Default recipient phone number (can be overridden in send)
        """
        self.gateway_url = gateway_url
        self.default_recipient = recipient
    
    def send(self, recipient: str, message: str) -> str:
        """
        Send WhatsApp message via gateway.
        
        Args:
            recipient: Phone number (e.g., "+1234567890")
            message: Message text to send
            
        Returns:
            WhatsApp message ID
            
        Raises:
            DeliveryError: If sending fails
        """
        # Use provided recipient or fall back to default
        target_recipient = recipient or self.default_recipient
        
        if not target_recipient:
            raise DeliveryError(
                ErrorCode.DELIVERY_RECIPIENT_INVALID,
                "No recipient specified"
            )
        
        # Check message length
        if len(message) > self.max_message_length():
            raise DeliveryError(
                ErrorCode.DELIVERY_MESSAGE_TOO_LONG,
                f"Message too long: {len(message)} chars"
            )
        
        # Build request payload
        payload = {
            "channel": "whatsapp",
            "to": target_recipient,
            "message": message
        }
        
        try:
            response = requests.post(
                self.gateway_url,
                json=payload,
                timeout=30,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'x-digest/0.1.0'
                }
            )
            
            # Parse response
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get("success"):
                    return response_data.get("messageId", "unknown")
                else:
                    # Gateway returned error
                    error = response_data.get("error", "Unknown error")
                    error_code = self._map_gateway_error(error)
                    raise DeliveryError(error_code, error)
            
            else:
                # HTTP error
                if response.status_code == 401:
                    raise DeliveryError(ErrorCode.DELIVERY_AUTH_FAILED)
                elif response.status_code == 429:
                    raise DeliveryError(ErrorCode.DELIVERY_RATE_LIMITED)
                elif response.status_code == 503:
                    raise DeliveryError(ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE)
                else:
                    raise DeliveryError(
                        ErrorCode.DELIVERY_SEND_FAILED,
                        f"HTTP {response.status_code}"
                    )
        
        except DeliveryError:
            raise
        except requests.Timeout:
            raise DeliveryError(ErrorCode.DELIVERY_NETWORK_ERROR, "Gateway timeout")
        except requests.ConnectionError:
            raise DeliveryError(ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE)
        except requests.RequestException as e:
            raise DeliveryError(ErrorCode.DELIVERY_NETWORK_ERROR, str(e))
        except Exception as e:
            raise DeliveryError(ErrorCode.DELIVERY_SEND_FAILED, str(e))
    
    def max_message_length(self) -> int:
        """WhatsApp message length limit."""
        return 4000  # Conservative limit for WhatsApp
    
    def _map_gateway_error(self, error: str) -> ErrorCode:
        """Map gateway error string to ErrorCode."""
        error_upper = error.upper()
        
        if "RECIPIENT_NOT_FOUND" in error_upper:
            return ErrorCode.WHATSAPP_RECIPIENT_NOT_FOUND
        elif "RATE_LIMITED" in error_upper:
            return ErrorCode.DELIVERY_RATE_LIMITED
        elif "AUTH_FAILED" in error_upper or "SESSION" in error_upper:
            return ErrorCode.WHATSAPP_SESSION_EXPIRED
        elif "GATEWAY_UNAVAILABLE" in error_upper:
            return ErrorCode.WHATSAPP_GATEWAY_UNAVAILABLE
        elif "MESSAGE_TOO_LONG" in error_upper:
            return ErrorCode.DELIVERY_MESSAGE_TOO_LONG
        else:
            return ErrorCode.DELIVERY_SEND_FAILED
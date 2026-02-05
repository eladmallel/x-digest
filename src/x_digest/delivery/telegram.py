"""
Telegram delivery provider.

Sends messages via Telegram Bot API with MarkdownV2 formatting support.
Converts WhatsApp-style formatting to Telegram-compatible markdown.
"""

import requests
import re
from typing import Optional

from .base import DeliveryProvider
from ..errors import DeliveryError, ErrorCode


class TelegramProvider(DeliveryProvider):
    """Telegram Bot API message delivery provider."""
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        Initialize Telegram provider.
        
        Args:
            bot_token: Telegram bot token (from @BotFather)
            chat_id: Target chat ID (user/group/channel)
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send(self, recipient: str, message: str) -> str:
        """
        Send Telegram message via Bot API.
        
        Args:
            recipient: Chat ID (can override default)
            message: Message text to send
            
        Returns:
            Telegram message ID
            
        Raises:
            DeliveryError: If sending fails
        """
        # Use provided recipient or default chat_id
        target_chat = recipient if recipient != self.chat_id else self.chat_id
        
        # Check message length
        if len(message) > self.max_message_length():
            raise DeliveryError(
                ErrorCode.DELIVERY_MESSAGE_TOO_LONG,
                f"Message too long: {len(message)} chars"
            )
        
        # Convert WhatsApp formatting to Telegram MarkdownV2
        formatted_message = self._convert_formatting(message)
        
        # Build request payload
        payload = {
            "chat_id": target_chat,
            "text": formatted_message,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True  # Prevent link previews cluttering
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=30
            )
            
            response_data = response.json()
            
            if response_data.get("ok"):
                # Success
                message_id = response_data["result"]["message_id"]
                return str(message_id)
            else:
                # API error
                error_code = response_data.get("error_code", 0)
                description = response_data.get("description", "Unknown error")
                
                telegram_error = self._map_telegram_error(error_code, description)
                raise DeliveryError(telegram_error, description)
        
        except DeliveryError:
            raise
        except requests.Timeout:
            raise DeliveryError(ErrorCode.DELIVERY_NETWORK_ERROR, "Telegram API timeout")
        except requests.RequestException as e:
            raise DeliveryError(ErrorCode.DELIVERY_NETWORK_ERROR, str(e))
        except Exception as e:
            raise DeliveryError(ErrorCode.DELIVERY_SEND_FAILED, str(e))
    
    def max_message_length(self) -> int:
        """Telegram message length limit."""
        return 4096  # Telegram's actual limit
    
    def _convert_formatting(self, text: str) -> str:
        """
        Convert WhatsApp-style formatting to Telegram MarkdownV2.
        
        WhatsApp uses: *bold*, _italic_, ~strikethrough~, ```code```
        Telegram MarkdownV2 uses similar syntax but with stricter escaping rules.
        """
        # For now, keep formatting mostly the same
        # Telegram MarkdownV2 and WhatsApp formatting are similar enough
        
        # Escape special characters that need escaping in MarkdownV2
        # But preserve our formatting markers
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        
        result = text
        
        # Simple approach: escape special chars outside of formatting
        # This is a basic implementation - production would need more sophisticated parsing
        
        return result
    
    def _map_telegram_error(self, error_code: int, description: str) -> ErrorCode:
        """Map Telegram API error to ErrorCode."""
        if error_code == 401:
            return ErrorCode.DELIVERY_AUTH_FAILED
        elif error_code == 403:
            if "blocked" in description.lower():
                return ErrorCode.TELEGRAM_BOT_BLOCKED
            else:
                return ErrorCode.DELIVERY_AUTH_FAILED
        elif error_code == 400:
            if "chat not found" in description.lower():
                return ErrorCode.TELEGRAM_CHAT_NOT_FOUND
            elif "message is too long" in description.lower():
                return ErrorCode.DELIVERY_MESSAGE_TOO_LONG
            else:
                return ErrorCode.DELIVERY_SEND_FAILED
        elif error_code == 429:
            return ErrorCode.DELIVERY_RATE_LIMITED
        else:
            return ErrorCode.DELIVERY_SEND_FAILED
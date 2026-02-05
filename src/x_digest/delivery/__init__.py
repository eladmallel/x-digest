"""
Message delivery providers for x-digest.

Provides pluggable delivery interfaces for different messaging platforms.
Supports WhatsApp, Telegram, and other channels with proper error handling
and retry logic.
"""

from .base import DeliveryProvider, get_provider
from .whatsapp import WhatsAppProvider
from .telegram import TelegramProvider

__all__ = ["DeliveryProvider", "get_provider", "WhatsAppProvider", "TelegramProvider"]
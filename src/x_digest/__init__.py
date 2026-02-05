"""
X-Digest: Twitter List Digest Pipeline

A tool that transforms curated Twitter lists into concise, LLM-generated digests 
delivered via WhatsApp, Telegram, or other channels.

This package provides a complete pipeline for:
- Fetching tweets from Twitter lists using bird CLI
- Pre-summarizing long content with LLM
- Generating organized digests with multimodal analysis
- Delivering via pluggable messaging providers

Key Features:
- Secure isolation (untrusted content never reaches main assistant)
- Pluggable LLM providers (Gemini, OpenAI, etc.)
- Pluggable delivery channels (WhatsApp, Telegram)
- Intelligent pre-processing for long threads and images
- Robust error handling and retry logic
- Complete pipeline monitoring and status tracking
"""

__version__ = "0.1.0"
__author__ = "Elad Mallel"
__license__ = "MIT"

# Core exports
from .errors import ErrorCode, BirdError, LLMError, DeliveryError, ConfigError
from .models import Tweet, Media
from .config import load_config

__all__ = [
    "ErrorCode", "BirdError", "LLMError", "DeliveryError", "ConfigError",
    "Tweet", "Media", 
    "load_config"
]
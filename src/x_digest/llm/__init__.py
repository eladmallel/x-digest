"""
LLM provider interface and implementations.

Provides a pluggable interface for different LLM providers (Gemini, OpenAI, etc.)
with support for text generation and multimodal (text + images) capabilities.

The interface standardizes LLM interactions across providers while allowing
provider-specific optimizations and features.
"""

from .base import LLMProvider
from .gemini import GeminiProvider

__all__ = ["LLMProvider", "GeminiProvider"]
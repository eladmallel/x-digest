"""
Base LLM provider interface.

Defines the abstract base class that all LLM providers must implement.
Provides a mock implementation for testing and development.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

from ..errors import LLMError, ErrorCode


class LLMProvider(ABC):
    """Base class for all LLM providers."""
    
    @abstractmethod
    def generate(self, prompt: str, system: str = "", images: List[Union[bytes, Dict[str, Any]]] = None) -> str:
        """
        Generate text from prompt, optionally with images.
        
        Args:
            prompt: The main prompt text
            system: System/instruction prompt (if supported)
            images: List of image data — either raw bytes or
                    Gemini inline_data dicts {"inline_data": {"mime_type": ..., "data": ...}}
            
        Returns:
            Generated text response
            
        Raises:
            LLMError: If generation fails
        """
        pass
    
    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Estimated token count
        """
        pass


@dataclass
class LLMCall:
    """Record of an LLM call for testing/debugging."""
    prompt: str
    system: str
    images: Optional[List[Union[bytes, Dict[str, Any]]]]
    response: str


class MockLLMProvider(LLMProvider):
    """
    Mock LLM provider for testing.
    
    Returns predefined responses and tracks all calls for assertions.
    """
    
    def __init__(self, response: str = "Mock response", error: Optional[LLMError] = None):
        """
        Initialize mock provider.
        
        Args:
            response: Fixed response to return
            error: Exception to raise instead of returning response
        """
        self.response = response
        self.error = error
        self.calls: List[LLMCall] = []
    
    def generate(self, prompt: str, system: str = "", images: List[Union[bytes, Dict[str, Any]]] = None) -> str:
        """Generate mock response and track call."""
        call = LLMCall(
            prompt=prompt,
            system=system,
            images=images,
            response=self.response if not self.error else ""
        )
        self.calls.append(call)
        
        if self.error:
            raise self.error
        
        return self.response
    
    def count_tokens(self, text: str) -> int:
        """Simple token estimation (words * 1.3)."""
        return int(len(text.split()) * 1.3)
    
    def reset(self):
        """Clear call history."""
        self.calls = []
    
    def set_response(self, response: str):
        """Change the response for future calls."""
        self.response = response
        self.error = None
    
    def set_error(self, error: LLMError):
        """Set error to raise for future calls."""
        self.error = error
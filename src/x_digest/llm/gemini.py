"""
Gemini LLM provider implementation.

Integrates with Google's Gemini API for text generation and multimodal analysis.
Supports both text-only and text+images prompts with proper error handling
and response parsing.
"""

import requests
import base64
from typing import List, Dict, Any, Optional

from .base import LLMProvider
from ..errors import LLMError, ErrorCode


class GeminiProvider(LLMProvider):
    """Gemini API provider for text generation and multimodal analysis."""
    
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        """
        Initialize Gemini provider.
        
        Args:
            api_key: Gemini API key
            model: Model name (default: gemini-2.0-flash)
        """
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
    
    def generate(self, prompt: str, system: str = "", images: List[bytes] = None) -> str:
        """
        Generate text using Gemini API.
        
        Args:
            prompt: Main prompt text
            system: System instruction (applied as first message)
            images: List of image data as bytes
            
        Returns:
            Generated text response
            
        Raises:
            LLMError: If API call fails or response is invalid
        """
        if images is None:
            images = []
        
        # Build request payload
        payload = self._build_payload(prompt, system, images)
        
        # Make API request
        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
        }
        params = {"key": self.api_key}
        
        try:
            response = requests.post(url, json=payload, headers=headers, params=params, timeout=30)
            
            if response.status_code == 401:
                raise LLMError(ErrorCode.LLM_API_AUTH, "Invalid Gemini API key")
            elif response.status_code == 429:
                raise LLMError(ErrorCode.LLM_RATE_LIMITED, "Gemini API rate limit exceeded")
            elif response.status_code == 403:
                raise LLMError(ErrorCode.LLM_QUOTA_EXCEEDED, "Gemini API quota exceeded")
            elif response.status_code != 200:
                raise LLMError(ErrorCode.LLM_INVALID_RESPONSE, f"HTTP {response.status_code}")
            
            response_data = response.json()
            return self._parse_response(response_data)
            
        except requests.Timeout:
            raise LLMError(ErrorCode.LLM_TIMEOUT)
        except requests.RequestException as e:
            raise LLMError(ErrorCode.LLM_NETWORK_ERROR, str(e))
        except Exception as e:
            raise LLMError(ErrorCode.LLM_INVALID_RESPONSE, str(e))
    
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Gemini uses roughly 1 token per 4 characters for English text.
        This is a rough approximation.
        """
        return len(text) // 4
    
    def _build_payload(self, prompt: str, system: str, images: List[bytes]) -> Dict[str, Any]:
        """Build Gemini API request payload."""
        contents = []
        
        # Add system instruction if provided
        if system:
            contents.append({
                "role": "user",
                "parts": [{"text": system}]
            })
        
        # Build parts for main message
        parts = [{"text": prompt}]
        
        # Add images if provided
        for img_bytes in images:
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",  # Default to JPEG
                    "data": img_base64
                }
            })
        
        contents.append({
            "role": "user",
            "parts": parts
        })
        
        return {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for consistent output
                "maxOutputTokens": 4000,
            }
        }
    
    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """Parse Gemini API response and extract text."""
        try:
            candidates = response_data.get("candidates", [])
            
            if not candidates:
                raise LLMError(ErrorCode.LLM_EMPTY_RESPONSE, "No candidates in response")
            
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            
            if not parts:
                raise LLMError(ErrorCode.LLM_EMPTY_RESPONSE, "No parts in response")
            
            # Find the text part
            text_parts = []
            for part in parts:
                if "text" in part:
                    text_parts.append(part["text"])
            
            if not text_parts:
                raise LLMError(ErrorCode.LLM_EMPTY_RESPONSE, "No text in response parts")
            
            return "".join(text_parts).strip()
            
        except LLMError:
            raise
        except KeyError as e:
            raise LLMError(ErrorCode.LLM_INVALID_RESPONSE, f"Missing field: {e}")
        except Exception as e:
            raise LLMError(ErrorCode.LLM_INVALID_RESPONSE, str(e))
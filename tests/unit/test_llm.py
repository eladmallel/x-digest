"""Tests for LLM provider interface and mock implementation."""

import pytest
from x_digest.llm.base import LLMProvider, MockLLMProvider, LLMCall
from x_digest.llm.gemini import GeminiProvider  
from x_digest.errors import LLMError, ErrorCode


def test_mock_provider_returns_fixture():
    """Mock provider returns configured response."""
    provider = MockLLMProvider(response="Test summary")
    result = provider.generate("any prompt")
    assert result == "Test summary"


def test_mock_provider_tracks_calls():
    """Mock provider tracks what was called.""" 
    provider = MockLLMProvider(response="Summary")
    provider.generate("prompt 1")
    provider.generate("prompt 2", system="sys")
    
    assert len(provider.calls) == 2
    assert provider.calls[0].prompt == "prompt 1"
    assert provider.calls[1].prompt == "prompt 2"
    assert provider.calls[1].system == "sys"


def test_mock_provider_with_images():
    """Mock provider accepts images."""
    provider = MockLLMProvider(response="Described image")
    result = provider.generate("Describe", images=[b"fake_image"])
    
    assert result == "Described image"
    assert provider.calls[0].images == [b"fake_image"]


def test_mock_provider_error():
    """Mock provider can raise configured errors."""
    error = LLMError(ErrorCode.LLM_TIMEOUT)
    provider = MockLLMProvider(error=error)
    
    with pytest.raises(LLMError) as exc:
        provider.generate("prompt")
    
    assert exc.value.code == ErrorCode.LLM_TIMEOUT


def test_provider_interface():
    """LLMProvider ABC enforces interface."""
    with pytest.raises(TypeError):
        LLMProvider()  # Can't instantiate abstract class


def test_mock_provider_methods():
    """Mock provider has all required methods."""
    provider = MockLLMProvider()
    
    # Test generate
    result = provider.generate("test")
    assert isinstance(result, str)
    
    # Test count_tokens
    tokens = provider.count_tokens("hello world")
    assert isinstance(tokens, int)
    assert tokens > 0
    
    # Test reset
    provider.reset()
    assert len(provider.calls) == 0
    
    # Test set_response
    provider.set_response("new response")
    assert provider.generate("test") == "new response"
    
    # Test set_error
    error = LLMError(ErrorCode.LLM_RATE_LIMITED)
    provider.set_error(error)
    with pytest.raises(LLMError):
        provider.generate("test")


def test_llm_call_dataclass():
    """LLMCall dataclass works correctly."""
    call = LLMCall(
        prompt="test prompt",
        system="test system", 
        images=[b"image_data"],
        response="test response"
    )
    
    assert call.prompt == "test prompt"
    assert call.system == "test system"
    assert call.images == [b"image_data"]
    assert call.response == "test response"


def test_mock_token_estimation():
    """Mock provider estimates tokens reasonably."""
    provider = MockLLMProvider()
    
    # Simple text
    tokens = provider.count_tokens("hello world")
    assert 2 <= tokens <= 5  # Should be roughly 2 words * 1.3
    
    # Longer text
    long_text = "This is a longer piece of text with many words"
    long_tokens = provider.count_tokens(long_text)
    assert long_tokens > tokens


# Basic Gemini provider tests (just structure, not API calls)
def test_gemini_provider_init():
    """Gemini provider initializes correctly."""
    provider = GeminiProvider(api_key="test_key")
    assert provider.api_key == "test_key"
    assert provider.model == "gemini-2.0-flash"  # default
    
    # Custom model
    provider = GeminiProvider(api_key="test", model="gemini-1.5-pro")
    assert provider.model == "gemini-1.5-pro"


def test_gemini_parse_response():
    """Parse actual Gemini response structure."""
    response = {
        "candidates": [{
            "content": {
                "parts": [{"text": "The summary"}]
            }
        }]
    }
    assert GeminiProvider._parse_response(None, response) == "The summary"


def test_gemini_parse_empty_response_raises():
    """Empty Gemini response raises LLMError."""
    response = {"candidates": []}
    
    with pytest.raises(LLMError) as exc:
        GeminiProvider._parse_response(None, response)
    assert exc.value.code == ErrorCode.LLM_EMPTY_RESPONSE


def test_gemini_build_text_payload():
    """Text-only payload has correct structure."""
    provider = GeminiProvider("test_key")
    payload = provider._build_payload("prompt text", system="system", images=[])
    
    assert "contents" in payload
    assert payload["contents"][0]["parts"][0]["text"] == "system"
    assert payload["contents"][1]["parts"][0]["text"] == "prompt text"


def test_gemini_build_multimodal_payload():
    """Multimodal payload includes images."""
    provider = GeminiProvider("test_key")
    payload = provider._build_payload("describe", system="", images=[b"img"])
    
    parts = payload["contents"][0]["parts"]
    assert any("inline_data" in str(part) for part in parts)


def test_gemini_token_estimation():
    """Gemini token estimation works."""
    provider = GeminiProvider("test_key")
    
    tokens = provider.count_tokens("Hello world!")
    assert tokens > 0
    assert isinstance(tokens, int)
    
    # Longer text should have more tokens
    long_tokens = provider.count_tokens("This is a much longer piece of text" * 10)
    assert long_tokens > tokens
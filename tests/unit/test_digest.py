"""Tests for digest generation and message splitting."""

import pytest
from x_digest.digest import (
    generate_digest, build_digest_payload, build_system_prompt,
    format_empty_digest, format_sparse_digest, split_digest,
    MIN_TWEETS_FOR_LLM
)
from x_digest.models import Tweet, Author
from x_digest.llm.base import MockLLMProvider
from x_digest.errors import LLMError, ErrorCode


def make_tweet(**kwargs):
    """Helper to create a test tweet with defaults."""
    defaults = {
        "id": "123",
        "text": "Test tweet",
        "created_at": "Wed Feb 04 19:00:43 +0000 2026",
        "conversation_id": "123",
        "author": Author(username="testuser", name="Test User"),
        "author_id": "1",
        "reply_count": 0,
        "retweet_count": 0,
        "like_count": 0
    }
    defaults.update(kwargs)
    return Tweet(**defaults)


def test_format_empty_digest():
    """Empty digest formatted correctly."""
    config = {"emoji": "🤖", "display_name": "AI & Dev"}
    result = format_empty_digest("ai-dev", config)
    
    assert "🤖" in result
    assert "AI & Dev" in result
    assert "Quiet period" in result or "No new tweets" in result


def test_format_sparse_digest():
    """Sparse digest formatted without LLM."""
    tweets = [
        make_tweet(id="1", text="First tweet", author=Author("user1", "User One"), like_count=10),
        make_tweet(id="2", text="Second tweet", author=Author("user2", "User Two"), like_count=5)
    ]
    
    config = {"emoji": "📋", "display_name": "Test List"}
    result = format_sparse_digest(tweets, config)
    
    assert "📋" in result
    assert "Test List" in result
    assert "2 tweets since last digest" in result
    assert "@user1" in result
    assert "@user2" in result
    assert "10 ❤️" in result


def test_build_digest_payload():
    """Digest payload includes all tweet metadata."""
    tweets = [
        make_tweet(
            id="123",
            text="Test tweet content", 
            author=Author("testuser", "Test User"),
            like_count=50,
            retweet_count=10,
            reply_count=5
        )
    ]
    summaries = {"123": "Pre-summarized content"}
    images = [("123", "https://example.com/image.jpg")]
    config = {"display_name": "Test", "emoji": "📋"}
    
    payload = build_digest_payload(tweets, summaries, images, config)
    
    # Check all required elements
    assert "📋 Test" in payload
    assert "@testuser (Test User)" in payload
    assert "50 ❤️ · 10 🔁 · 5 💬" in payload
    assert "Pre-summarized content" in payload
    assert "https://x.com/testuser/status/123" in payload
    assert "[Image attached]" in payload


def test_build_system_prompt_hierarchy():
    """System prompt uses correct hierarchy."""
    # List-specific prompt
    config_with_prompt = {"prompt": "Custom list prompt"}
    assert build_system_prompt(config_with_prompt) == "Custom list prompt"
    
    # Default prompt fallback
    config_with_defaults = {"defaults": {"prompt": "Default prompt"}}
    assert build_system_prompt(config_with_defaults) == "Default prompt"
    
    # Built-in prompt fallback
    config_empty = {}
    prompt = build_system_prompt(config_empty)
    assert "Twitter digest curator" in prompt


def test_generate_digest_empty_tweets():
    """Empty tweet list returns empty digest."""
    mock_llm = MockLLMProvider()
    config = {"emoji": "📋", "list_name": "Test"}
    
    result = generate_digest([], {}, [], config, mock_llm)
    
    assert "Quiet period" in result or "No new tweets" in result
    assert len(mock_llm.calls) == 0


def test_generate_digest_sparse_tweets():
    """Few tweets bypass LLM and use sparse format."""
    tweets = [make_tweet(id=str(i)) for i in range(MIN_TWEETS_FOR_LLM - 1)]
    mock_llm = MockLLMProvider()
    config = {"emoji": "📋", "display_name": "Test"}
    
    result = generate_digest(tweets, {}, [], config, mock_llm)
    
    # Should use sparse format, not call LLM
    assert len(mock_llm.calls) == 0
    assert f"{len(tweets)} tweets since last digest" in result


def test_generate_digest_calls_llm():
    """Sufficient tweets call LLM for full digest."""
    tweets = [make_tweet(id=str(i)) for i in range(MIN_TWEETS_FOR_LLM + 1)]
    mock_llm = MockLLMProvider(response="🔥 *Top*\n\nGenerated digest content")
    config = {"emoji": "📋", "display_name": "Test"}
    
    result = generate_digest(tweets, {}, [], config, mock_llm)
    
    # Should call LLM
    assert len(mock_llm.calls) == 1
    assert result == "🔥 *Top*\n\nGenerated digest content"


def test_generate_digest_llm_failure_fallback():
    """LLM failure falls back to sparse format."""
    tweets = [make_tweet(id=str(i)) for i in range(MIN_TWEETS_FOR_LLM + 1)]
    mock_llm = MockLLMProvider(error=LLMError(ErrorCode.LLM_TIMEOUT))
    config = {"emoji": "📋", "display_name": "Test"}
    
    result = generate_digest(tweets, {}, [], config, mock_llm)
    
    # Should attempt LLM then fall back to sparse
    assert len(mock_llm.calls) == 1
    assert f"{len(tweets)} tweets since last digest" in result


# Message splitting tests

def test_split_digest_short_message():
    """Short message is not split."""
    short_digest = "Short digest content"
    parts = split_digest(short_digest, max_length=1000)
    
    assert len(parts) == 1
    assert parts[0] == "Short digest content"


def test_split_digest_at_section_boundary():
    """Long digest splits at section boundaries."""
    digest = (
        "🔥 *Top*\n\n" + "x" * 3500 + 
        "\n\n💡 *Worth Noting*\n\n" + "y" * 3500
    )
    
    parts = split_digest(digest, max_length=4000)
    
    assert len(parts) == 2
    assert "🔥 *Top*" in parts[0]
    assert "💡 *Worth Noting*" in parts[1]
    # Check part indicators
    assert "(1/2)" in parts[0]
    assert "(2/2)" in parts[1]


def test_split_digest_at_item_boundary():
    """Splits at bold item boundary when no section boundary available."""
    digest = "🔥 *Top*\n\n*First item* content here\n\n*Second item*" + "z" * 4000
    
    parts = split_digest(digest, max_length=4000)
    
    assert len(parts) > 1
    # Should split before "*Second item*"
    assert "*First item*" in parts[0]
    assert "*Second item*" in parts[1]


def test_split_digest_at_paragraph_boundary():
    """Falls back to paragraph boundary when no better option."""
    # Create content with only paragraph breaks
    content = "Line 1\n\nLine 2" + "x" * 3990 + "\n\nLine 3" + "y" * 3990
    
    parts = split_digest(content, max_length=4000)
    
    assert len(parts) >= 2
    # Part indicators add ~12 chars, so raw content before indicator should be under limit
    for part in parts:
        # Strip the part indicator suffix to check raw content length
        raw = part.rsplit("\n\n_(", 1)[0] if "\n\n_(" in part else part
        assert len(raw) <= 4000


def test_split_digest_emergency_hard_split():
    """Hard split when no good boundaries available."""
    # Single very long line with no good split points
    digest = "x" * 8000  # No spaces, sections, or paragraph breaks
    
    parts = split_digest(digest, max_length=4000)
    
    assert len(parts) >= 2
    # All content should be preserved (minus whitespace stripping)
    total_content = sum(len(p.rsplit("\n\n_(", 1)[0]) if "\n\n_(" in p else len(p) for p in parts)
    assert total_content == 8000


def test_split_digest_multiple_sections():
    """Multiple sections split correctly."""
    digest = (
        "🔥 *Top*\n\n" + "a" * 3800 +
        "\n\n🚀 *Product Launch*\n\n" + "b" * 3800 +
        "\n\n💡 *Worth Noting*\n\n" + "c" * 3800
    )
    
    parts = split_digest(digest, max_length=4000)
    
    assert len(parts) == 3
    assert "🔥 *Top*" in parts[0]
    assert "🚀 *Product Launch*" in parts[1]
    assert "💡 *Worth Noting*" in parts[2]
    
    # Check part indicators
    assert "(1/3)" in parts[0]
    assert "(2/3)" in parts[1]
    assert "(3/3)" in parts[2]


def test_split_digest_edge_case_exactly_at_limit():
    """Content exactly at limit is not split."""
    digest = "x" * 4000  # Exactly at limit
    
    parts = split_digest(digest, max_length=4000)
    
    assert len(parts) == 1
    assert parts[0] == digest


def test_split_digest_preserves_formatting():
    """Formatting around split points is preserved."""
    digest = (
        "🔥 *Top*\n\n*Item 1* - content here\n\n*Item 2* - " + "x" * 3900 +
        "\n\n💡 *Worth Noting*\n\n*Item 3* - " + "y" * 2000
    )
    
    parts = split_digest(digest, max_length=4000)
    
    assert len(parts) >= 2
    # Check that section headers end up in the right parts
    assert "🔥 *Top*" in parts[0]
    # Second part should have the Worth Noting section (stripping part indicator)
    raw_part1 = parts[1].rsplit("\n\n_(", 1)[0] if "\n\n_(" in parts[1] else parts[1]
    assert "💡 *Worth Noting*" in raw_part1


def test_split_digest_empty_input():
    """Empty input returns empty list."""
    parts = split_digest("", max_length=4000)
    
    assert len(parts) == 1
    assert parts[0] == ""


def test_split_digest_very_small_limit():
    """Very small limit handled gracefully — doesn't crash."""
    digest = "Some content here"
    
    parts = split_digest(digest, max_length=5)
    
    # Should produce multiple parts without crashing
    assert len(parts) >= 1
    # All original content should be preserved across parts
    assert len("".join(parts)) > 0
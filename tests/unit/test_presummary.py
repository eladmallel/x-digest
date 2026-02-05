"""Tests for pre-summarization decision logic and prompt building."""

import pytest
from x_digest.models import Tweet, Author
from x_digest.presummary import should_presummary, build_presummary_prompt, presummary_tweets
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


def test_short_tweet_no_presummary():
    """Tweet under 500 chars doesn't need presummary."""
    tweet = make_tweet(text="Short tweet")
    assert should_presummary(tweet) is False


def test_long_tweet_needs_presummary():
    """Tweet over 500 chars needs presummary.""" 
    long_text = "x" * 600
    tweet = make_tweet(text=long_text)
    assert should_presummary(tweet) is True


def test_long_quote_needs_presummary():
    """Quote tweet where quoted content > 300 chars needs presummary."""
    quoted_text = "y" * 400  # Over 300 char limit for quotes
    quoted = make_tweet(text=quoted_text)
    tweet = make_tweet(text="Short comment", quoted_tweet=quoted)
    assert should_presummary(tweet) is True


def test_short_quote_no_presummary():
    """Quote with short content doesn't need presummary."""
    quoted = make_tweet(text="Short quoted content")
    tweet = make_tweet(text="Short comment", quoted_tweet=quoted)
    assert should_presummary(tweet) is False


def test_thread_needs_presummary():
    """Thread with 2+ tweets needs presummary."""
    thread = [
        make_tweet(id="1", text="First tweet"),
        make_tweet(id="2", text="Second tweet")
    ]
    assert should_presummary(thread) is True


def test_single_short_thread_no_presummary():
    """Single-tweet 'thread' under length doesn't need presummary."""
    thread = [make_tweet(text="Solo tweet")]
    assert should_presummary(thread) is False


def test_single_long_thread_needs_presummary():
    """Single-tweet thread over length threshold needs presummary."""
    long_text = "x" * 600
    thread = [make_tweet(text=long_text)]
    assert should_presummary(thread) is True


def test_combined_length_threshold():
    """Combined content length triggers presummary."""
    # Each part is under individual limits, but combined is over 600 chars
    tweet_text = "x" * 300
    quote_text = "y" * 350
    quoted = make_tweet(text=quote_text)
    tweet = make_tweet(text=tweet_text, quoted_tweet=quoted)
    
    assert should_presummary(tweet) is True


def test_custom_config_thresholds():
    """Custom configuration thresholds are respected."""
    config = {
        "pre_summarization": {
            "long_tweet_chars": 100,  # Lower threshold
            "long_quote_chars": 50,
            "long_combined_chars": 150,
            "thread_min_tweets": 3  # Higher threshold
        }
    }
    
    # Tweet that would be short with defaults but long with custom config
    tweet = make_tweet(text="x" * 120)  # Over custom 100 char limit
    assert should_presummary(tweet, config) is True
    
    # Thread that needs 3+ tweets with custom config
    two_tweet_thread = [make_tweet(id="1"), make_tweet(id="2")]
    assert should_presummary(two_tweet_thread, config) is False
    
    three_tweet_thread = [make_tweet(id="1"), make_tweet(id="2"), make_tweet(id="3")]
    assert should_presummary(three_tweet_thread, config) is True


def test_prompt_includes_author():
    """Prompt includes author username."""
    content = "Tweet content here"
    prompt = build_presummary_prompt(content, "long_tweet", "simonw")
    assert "@simonw" in prompt


def test_prompt_includes_content_type():
    """Prompt includes content type."""
    content = "Content here"
    prompt = build_presummary_prompt(content, "thread", "user")
    assert "thread" in prompt.lower()


def test_prompt_includes_length():
    """Prompt includes original length."""
    content = "x" * 1000
    prompt = build_presummary_prompt(content, "long_tweet", "user")
    assert "1000 chars" in prompt or "1,000 chars" in prompt


def test_prompt_includes_content():
    """Prompt includes the actual content."""
    content = "My actual tweet text with specific details"
    prompt = build_presummary_prompt(content, "long_tweet", "user")
    assert "My actual tweet text with specific details" in prompt


def test_prompt_thread_format():
    """Thread prompt includes tweet count."""
    content = "Tweet 1\n---\nTweet 2\n---\nTweet 3"
    prompt = build_presummary_prompt(content, "thread", "author")
    
    assert "thread" in prompt.lower()
    assert "3 tweets" in prompt or "chars / 3" in prompt


def test_prompt_instructions():
    """Prompt includes all required instructions."""
    content = "Sample content"
    prompt = build_presummary_prompt(content, "long_tweet", "user")
    
    # Check for key instruction elements
    assert "2 paragraphs" in prompt
    assert "4-6 sentences" in prompt
    assert "core message" in prompt
    assert "supporting details" in prompt
    assert "author's perspective" in prompt
    assert "technical details" in prompt
    assert "OUTPUT: Just the summary" in prompt


def test_prompt_different_content_types():
    """Different content types generate appropriate prompts."""
    content = "Sample content"
    
    # Long tweet
    prompt_tweet = build_presummary_prompt(content, "long_tweet", "user")
    assert "long_tweet" in prompt_tweet
    
    # Thread  
    prompt_thread = build_presummary_prompt(content, "thread", "user")
    assert "thread" in prompt_thread
    
    # Quote chain
    prompt_quote = build_presummary_prompt(content, "quote_chain", "user")
    assert "quote_chain" in prompt_quote
    
    # All should have common elements
    for prompt in [prompt_tweet, prompt_thread, prompt_quote]:
        assert "CONTENT:" in prompt
        assert "INSTRUCTIONS:" in prompt
        assert "@user" in prompt


def test_empty_thread_handling():
    """Empty thread list doesn't need presummary."""
    assert should_presummary([]) is False


def test_none_config_handling():
    """None config uses defaults."""
    tweet = make_tweet(text="x" * 600)  # Over default 500 char limit
    assert should_presummary(tweet, None) is True
    
    short_tweet = make_tweet(text="short")
    assert should_presummary(short_tweet, None) is False


# Pre-summarization pipeline tests (milestone 2.4)

def test_presummary_tweets_skips_short_tweets():
    """Short tweets are not sent to LLM."""
    tweets = [
        make_tweet(id="1", conversation_id="1", text="short"),
        make_tweet(id="2", conversation_id="2", text="also short")
    ]
    
    mock_llm = MockLLMProvider(response="Should not be called")
    results = presummary_tweets(tweets, mock_llm)
    
    # No LLM calls should be made
    assert len(mock_llm.calls) == 0
    
    # All results should have None summary
    assert len(results) == 2
    assert results[0][1] is None  # First tweet, no summary
    assert results[1][1] is None  # Second tweet, no summary


def test_presummary_tweets_calls_llm_for_long():
    """Long tweets are sent to LLM for summarization."""
    tweets = [
        make_tweet(id="1", conversation_id="1", text="x" * 600),  # Over 500 char limit
        make_tweet(id="2", conversation_id="2", text="short")
    ]
    
    mock_llm = MockLLMProvider(response="Summarized content")
    results = presummary_tweets(tweets, mock_llm)
    
    # One LLM call for the long tweet
    assert len(mock_llm.calls) == 1
    assert "x" * 600 in mock_llm.calls[0].prompt
    
    # Results: long tweet has summary, short doesn't
    assert len(results) == 2
    # Find results by tweet id (order may vary due to dict iteration)
    result_map = {r[0].id: r[1] for r in results}
    assert result_map["1"] == "Summarized content"  # Long tweet
    assert result_map["2"] is None  # Short tweet


def test_presummary_tweets_handles_llm_failure():
    """LLM failure returns None summary but continues processing."""
    tweets = [
        make_tweet(id="1", conversation_id="1", text="x" * 600),
        make_tweet(id="2", conversation_id="2", text="y" * 600)
    ]
    
    # Mock LLM that fails
    mock_llm = MockLLMProvider(error=LLMError(ErrorCode.LLM_TIMEOUT))
    results = presummary_tweets(tweets, mock_llm)
    
    # LLM was called for both but failed
    assert len(mock_llm.calls) == 2
    
    # Both summaries should be None due to failures
    assert len(results) == 2
    assert results[0][1] is None
    assert results[1][1] is None


def test_presummary_tweets_handles_threads():
    """Multi-tweet threads are summarized as a unit."""
    tweets = [
        make_tweet(id="1", conversation_id="1", text="First tweet"),
        make_tweet(id="2", conversation_id="1", text="Second tweet", 
                  in_reply_to_status_id="1")
    ]
    
    mock_llm = MockLLMProvider(response="Thread summary")
    results = presummary_tweets(tweets, mock_llm)
    
    # One LLM call for the thread
    assert len(mock_llm.calls) == 1
    call = mock_llm.calls[0]
    assert "Tweet 1: First tweet" in call.prompt
    assert "Tweet 2: Second tweet" in call.prompt
    
    # Both tweets get the same thread summary
    assert len(results) == 2
    assert results[0][1] == "Thread summary"
    assert results[1][1] == "Thread summary"


def test_presummary_tweets_mixed_content():
    """Mixed batch with threads and singles processed correctly."""
    tweets = [
        # Single long tweet
        make_tweet(id="1", conversation_id="1", text="x" * 600),
        # Thread (2 tweets)
        make_tweet(id="2", conversation_id="2", text="Thread start"),
        make_tweet(id="3", conversation_id="2", text="Thread continue",
                  in_reply_to_status_id="2"),
        # Short single tweet (no summary needed)
        make_tweet(id="4", conversation_id="4", text="short")
    ]
    
    mock_llm = MockLLMProvider(response="Summary")
    results = presummary_tweets(tweets, mock_llm)
    
    # Two LLM calls: one for single long tweet, one for thread
    assert len(mock_llm.calls) == 2
    
    # Check results
    assert len(results) == 4
    assert results[0][1] == "Summary"  # Long single tweet
    assert results[1][1] == "Summary"  # Thread tweet 1
    assert results[2][1] == "Summary"  # Thread tweet 2  
    assert results[3][1] is None       # Short tweet


def test_presummary_quote_tweet_with_long_content():
    """Quote tweet with long quoted content is summarized."""
    quoted = make_tweet(id="quoted", text="y" * 400)  # Long quoted content
    tweet = make_tweet(id="1", text="Interesting point:", quoted_tweet=quoted)
    
    mock_llm = MockLLMProvider(response="Quote summary")
    results = presummary_tweets([tweet], mock_llm)
    
    # One LLM call
    assert len(mock_llm.calls) == 1
    call = mock_llm.calls[0]
    assert "Interesting point:" in call.prompt
    assert "y" * 400 in call.prompt
    assert "QUOTED CONTENT:" in call.prompt
    
    # Tweet gets summary
    assert results[0][1] == "Quote summary"


def test_presummary_respects_custom_config():
    """Custom configuration thresholds are respected."""
    custom_config = {
        "pre_summarization": {
            "enabled": True,
            "long_tweet_chars": 100,  # Lower threshold
            "thread_min_tweets": 3    # Require 3+ tweets for thread summary
        }
    }
    
    tweets = [
        make_tweet(id="1", text="x" * 150),  # Over custom 100 char limit
        # 2-tweet thread (under custom 3-tweet minimum)
        make_tweet(id="2", conversation_id="2", text="Thread 1"),
        make_tweet(id="3", conversation_id="2", text="Thread 2",
                  in_reply_to_status_id="2")
    ]
    
    mock_llm = MockLLMProvider(response="Custom summary")
    results = presummary_tweets(tweets, mock_llm, custom_config)
    
    # Only one call for the long single tweet (thread doesn't meet 3+ requirement)
    assert len(mock_llm.calls) == 1
    assert results[0][1] == "Custom summary"  # Long tweet
    assert results[1][1] is None  # Thread tweet 1 (no summary) 
    assert results[2][1] is None  # Thread tweet 2 (no summary)


def test_presummary_disabled_config():
    """Pre-summarization can be disabled via config."""
    disabled_config = {
        "pre_summarization": {
            "enabled": False
        }
    }
    
    tweets = [make_tweet(text="x" * 1000)]  # Very long tweet
    
    mock_llm = MockLLMProvider(response="Should not be called")
    results = presummary_tweets(tweets, mock_llm, disabled_config)
    
    # No LLM calls when disabled
    assert len(mock_llm.calls) == 0
    assert results[0][1] is None
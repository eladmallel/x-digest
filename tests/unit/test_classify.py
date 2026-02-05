"""Tests for tweet classification and thread reconstruction."""

import json
import pytest
from pathlib import Path
from x_digest.models import Tweet, Author, parse_tweets
from x_digest.classify import (
    TweetType, classify_tweet, reconstruct_threads, 
    classify_thread_completeness, dedupe_quotes,
    categorize_tweets, get_thread_stats
)


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


def load_fixture(filename):
    """Load test fixture data."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "tweets" / filename
    with open(fixture_path) as f:
        return json.load(f)


def test_classify_standalone():
    """Standalone tweet: conversation_id == id, no in_reply_to_status_id."""
    tweet = make_tweet(id="1", conversation_id="1", in_reply_to_status_id=None)
    assert classify_tweet(tweet) == TweetType.STANDALONE


def test_classify_reply():
    """Reply: has in_reply_to_status_id."""
    tweet = make_tweet(id="2", conversation_id="1", in_reply_to_status_id="1")
    assert classify_tweet(tweet) == TweetType.REPLY


def test_classify_quote():
    """Quote tweet: has quoted_tweet field."""
    quoted = make_tweet(id="99")
    tweet = make_tweet(id="3", quoted_tweet=quoted)
    assert classify_tweet(tweet) == TweetType.QUOTE


def test_classify_retweet():
    """Retweet: text starts with RT @."""
    tweet = make_tweet(id="4", text="RT @someone: original content")
    assert classify_tweet(tweet) == TweetType.RETWEET


def test_reconstruct_simple_thread():
    """5-tweet thread groups correctly."""
    tweets_data = load_fixture("thread_5_tweets.json")
    tweets = parse_tweets(tweets_data)
    
    threads = reconstruct_threads(tweets)
    assert len(threads) == 1
    
    thread = list(threads.values())[0]
    assert len(thread) == 5
    
    # Verify chronological order
    for i in range(len(thread) - 1):
        # Should be in chronological order (earlier tweets first)
        assert thread[i].id < thread[i+1].id  # Simplified check using ID order


def test_reconstruct_mixed_tweets():
    """Mixed standalone and thread tweets separate correctly."""
    # Create a mix of tweets
    tweets = [
        make_tweet(id="1", conversation_id="1"),  # Standalone
        make_tweet(id="2", conversation_id="2"),  # Thread start
        make_tweet(id="3", conversation_id="2", in_reply_to_status_id="2"),  # Thread continuation
        make_tweet(id="4", conversation_id="4"),  # Another standalone
    ]
    
    threads = reconstruct_threads(tweets)
    assert len(threads) == 3  # Three conversation threads
    
    # Check thread sizes
    thread_sizes = [len(thread) for thread in threads.values()]
    assert sorted(thread_sizes) == [1, 1, 2]  # Two single tweets, one 2-tweet thread


def test_thread_completeness_complete():
    """Complete thread: has root, no gaps."""
    tweets_data = load_fixture("thread_5_tweets.json")
    tweets = parse_tweets(tweets_data)
    threads = reconstruct_threads(tweets)
    
    thread = list(threads.values())[0]
    completeness = classify_thread_completeness(thread)
    assert completeness == "complete"


def test_thread_completeness_partial_no_root():
    """Partial thread: missing root tweet."""
    # Create thread starting from tweet 2 (missing tweet 1)
    tweets = [
        make_tweet(id="2", conversation_id="1", in_reply_to_status_id="1"),
        make_tweet(id="3", conversation_id="1", in_reply_to_status_id="2"),
    ]
    
    completeness = classify_thread_completeness(tweets)
    assert completeness == "partial_no_root"


def test_thread_completeness_single_tweet():
    """Single tweet is always complete."""
    tweet = make_tweet(id="1", conversation_id="1")
    completeness = classify_thread_completeness([tweet])
    assert completeness == "complete"


def test_dedupe_removes_quoted():
    """Quoted tweet removed when quote tweet present."""
    tweets_data = load_fixture("quote_with_quoted.json")
    tweets = parse_tweets(tweets_data)
    
    original_count = len(tweets)
    deduped = dedupe_quotes(tweets)
    
    # Should have removed the quoted standalone tweet
    assert len(deduped) == original_count - 1
    
    # The quoted tweet should be gone, but quote tweet should remain
    quoted_id = "2019123973615939775"  # The original tweet that gets quoted
    quote_id = "2019123973615939780"   # The quote tweet
    
    deduped_ids = {t.id for t in deduped}
    assert quoted_id not in deduped_ids  # Original quoted tweet removed
    assert quote_id in deduped_ids       # Quote tweet kept


def test_dedupe_keeps_quote():
    """Quote tweet is kept."""
    tweets_data = load_fixture("quote_with_quoted.json")
    tweets = parse_tweets(tweets_data)
    deduped = dedupe_quotes(tweets)
    
    # The quote tweet should remain and still have quoted content
    quote_tweet = next(t for t in deduped if t.quoted_tweet is not None)
    assert quote_tweet is not None
    assert quote_tweet.quoted_tweet is not None


def test_dedupe_no_effect_without_quotes():
    """Batch without quotes unchanged."""
    tweets_data = load_fixture("thread_5_tweets.json")
    tweets = parse_tweets(tweets_data)
    
    deduped = dedupe_quotes(tweets)
    assert len(deduped) == len(tweets)


def test_categorize_tweets():
    """Tweets are categorized correctly."""
    tweets = [
        make_tweet(id="1", conversation_id="1"),  # Standalone
        make_tweet(id="2", conversation_id="2", text="RT @user: content"),  # Retweet
        make_tweet(id="3", conversation_id="3", quoted_tweet=make_tweet(id="99")),  # Quote
        make_tweet(id="4", conversation_id="4", in_reply_to_status_id="100"),  # Reply
        make_tweet(id="5", conversation_id="5"),  # Thread start
        make_tweet(id="6", conversation_id="5", in_reply_to_status_id="5"),  # Thread continuation
    ]
    
    categories = categorize_tweets(tweets)
    
    assert len(categories["standalone"]) == 1
    assert len(categories["retweets"]) == 1
    assert len(categories["quotes"]) == 1
    assert len(categories["replies"]) == 1
    assert len(categories["threads"]) == 1  # One thread containing 2 tweets
    assert len(categories["threads"][0]) == 2  # The thread has 2 tweets


def test_get_thread_stats():
    """Thread statistics are calculated correctly."""
    # Mix of single tweets and a multi-tweet thread
    threads = {
        "1": [make_tweet(id="1", conversation_id="1")],  # Single
        "2": [make_tweet(id="2", conversation_id="2")],  # Single
        "3": [  # Multi-tweet thread
            make_tweet(id="3", conversation_id="3"),
            make_tweet(id="4", conversation_id="3")
        ]
    }
    
    stats = get_thread_stats(threads)
    
    assert stats["total_threads"] == 3
    assert stats["single_tweets"] == 2
    assert stats["multi_tweet_threads"] == 1
    assert stats["total_tweets"] == 4
    assert stats["complete_threads"] == 3  # All are complete in this test


# Thread gap handling tests

def test_thread_with_gaps_detected():
    """Thread with missing tweets in middle is detected as partial_with_root."""
    tweets = [
        make_tweet(id="1", conversation_id="1"),  # Root tweet
        make_tweet(id="3", conversation_id="1", in_reply_to_status_id="2")  # Replies to missing tweet "2"
    ]
    
    completeness = classify_thread_completeness(tweets)
    assert completeness == "partial_with_root"


def test_thread_missing_root():
    """Thread without root tweet is detected as partial_no_root."""
    tweets = [
        make_tweet(id="2", conversation_id="1", in_reply_to_status_id="1"),  # Missing root "1"
        make_tweet(id="3", conversation_id="1", in_reply_to_status_id="2")
    ]
    
    completeness = classify_thread_completeness(tweets)
    assert completeness == "partial_no_root"


def test_complete_thread_no_gaps():
    """Complete thread has root and no gaps."""
    tweets = [
        make_tweet(id="1", conversation_id="1"),  # Root
        make_tweet(id="2", conversation_id="1", in_reply_to_status_id="1"),
        make_tweet(id="3", conversation_id="1", in_reply_to_status_id="2")
    ]
    
    completeness = classify_thread_completeness(tweets)
    assert completeness == "complete"


def test_thread_stats_with_partial_threads():
    """Thread statistics correctly count different completeness types."""
    tweets = [
        # Complete thread
        make_tweet(id="1", conversation_id="1"),
        make_tweet(id="2", conversation_id="1", in_reply_to_status_id="1"),
        
        # Partial with root (has gap)
        make_tweet(id="10", conversation_id="10"),  # Root
        make_tweet(id="12", conversation_id="10", in_reply_to_status_id="11"),  # Missing tweet 11
        
        # Partial no root (conversation started by missing tweet 19)
        make_tweet(id="20", conversation_id="19", in_reply_to_status_id="19"),  # Root 19 is missing
        make_tweet(id="21", conversation_id="19", in_reply_to_status_id="20"),
        
        # Standalone
        make_tweet(id="30", conversation_id="30")
    ]
    
    threads = reconstruct_threads(tweets)
    stats = get_thread_stats(threads)
    
    assert stats["complete_threads"] == 2  # Complete thread + standalone
    assert stats["partial_with_root"] == 1
    assert stats["partial_no_root"] == 1
    assert stats["total_threads"] == 4


def test_empty_thread_completeness():
    """Empty thread list returns complete."""
    completeness = classify_thread_completeness([])
    assert completeness == "complete"


def test_single_tweet_always_complete():
    """Single tweet is always considered complete."""
    tweet = make_tweet(id="1", conversation_id="1")
    completeness = classify_thread_completeness([tweet])
    assert completeness == "complete"
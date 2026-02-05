"""Integration test: Fetch fixtures → classify → verify grouping."""

import json
import pytest

from x_digest.models import parse_tweets
from x_digest.classify import (
    classify_tweet,
    TweetType,
    reconstruct_threads,
    categorize_tweets,
    dedupe_quotes,
    classify_thread_completeness,
    get_thread_stats,
)

from .conftest import load_fixture, load_fixture_raw


class TestSingleTweetFixture:
    """Tests with single_tweet.json fixture."""

    def test_parse_single_tweet(self):
        """Single tweet fixture parses correctly."""
        tweets = load_fixture("single_tweet.json")
        assert len(tweets) == 1
        assert tweets[0].id == "2019123973615939775"
        assert tweets[0].author.username == "devlead"

    def test_classify_as_standalone(self):
        """Single tweet is classified as standalone."""
        tweets = load_fixture("single_tweet.json")
        assert classify_tweet(tweets[0]) == TweetType.STANDALONE


class TestThreadFixture:
    """Tests with thread_5_tweets.json fixture."""

    def test_parse_thread(self):
        """5-tweet thread fixture parses all tweets."""
        tweets = load_fixture("thread_5_tweets.json")
        assert len(tweets) == 5

    def test_reconstruct_thread(self):
        """Thread tweets group under one conversation ID."""
        tweets = load_fixture("thread_5_tweets.json")
        threads = reconstruct_threads(tweets)
        assert len(threads) == 1
        thread = list(threads.values())[0]
        assert len(thread) == 5

    def test_thread_order(self):
        """Thread tweets are sorted chronologically."""
        tweets = load_fixture("thread_5_tweets.json")
        threads = reconstruct_threads(tweets)
        thread = list(threads.values())[0]
        for i in range(len(thread) - 1):
            assert thread[i].created_at <= thread[i + 1].created_at

    def test_thread_completeness(self):
        """5-tweet thread is detected as complete."""
        tweets = load_fixture("thread_5_tweets.json")
        threads = reconstruct_threads(tweets)
        thread = list(threads.values())[0]
        assert classify_thread_completeness(thread) == "complete"


class TestQuoteFixture:
    """Tests with quote_with_quoted.json fixture."""

    def test_parse_quote(self):
        """Quote fixture parses both tweets."""
        tweets = load_fixture("quote_with_quoted.json")
        assert len(tweets) == 2

    def test_dedupe_removes_quoted(self):
        """Dedupe removes the quoted standalone tweet."""
        tweets = load_fixture("quote_with_quoted.json")
        deduped = dedupe_quotes(tweets)
        assert len(deduped) == 1
        # The remaining tweet should be the one with quotedTweet
        assert deduped[0].quoted_tweet is not None

    def test_classify_as_quote(self):
        """Quote tweet is classified as QUOTE type."""
        tweets = load_fixture("quote_with_quoted.json")
        quote_tweet = [t for t in tweets if t.quoted_tweet][0]
        assert classify_tweet(quote_tweet) == TweetType.QUOTE


class TestPartialThreadFixture:
    """Tests with partial_thread.json fixture."""

    def test_parse_partial(self):
        """Partial thread fixture parses correctly."""
        tweets = load_fixture("partial_thread.json")
        assert len(tweets) == 3

    def test_partial_no_root(self):
        """Partial thread missing root is detected."""
        tweets = load_fixture("partial_thread.json")
        threads = reconstruct_threads(tweets)
        thread = list(threads.values())[0]
        assert classify_thread_completeness(thread) == "partial_no_root"


class TestEmptyFixture:
    """Tests with empty.json fixture."""

    def test_parse_empty(self):
        """Empty fixture returns empty list."""
        tweets = load_fixture("empty.json")
        assert len(tweets) == 0


class TestLongTweetFixture:
    """Tests with long_tweet.json fixture."""

    def test_parse_long_tweet(self):
        """Long tweet fixture parses correctly."""
        tweets = load_fixture("long_tweet.json")
        assert len(tweets) == 1
        assert len(tweets[0].text) > 500  # Should be a long tweet

    def test_classify_as_standalone(self):
        """Long tweet is standalone."""
        tweets = load_fixture("long_tweet.json")
        assert classify_tweet(tweets[0]) == TweetType.STANDALONE


class TestWithImagesFixture:
    """Tests with with_images.json fixture."""

    def test_parse_with_images(self):
        """Image fixture parses media correctly."""
        tweets = load_fixture("with_images.json")
        assert len(tweets) == 3
        # First tweet should have 2 photos
        assert tweets[0].media is not None
        assert len(tweets[0].media) == 2
        assert all(m.type == "photo" for m in tweets[0].media)

    def test_video_media(self):
        """Video media parses correctly."""
        tweets = load_fixture("with_images.json")
        video_tweet = [t for t in tweets if t.media and any(m.type == "video" for m in t.media)][0]
        video = [m for m in video_tweet.media if m.type == "video"][0]
        assert video.video_url is not None
        assert video.duration_ms is not None


class TestMixedBatch50Fixture:
    """Tests with mixed_batch_50.json fixture."""

    def test_parse_all_50(self):
        """Mixed batch fixture parses all 50 tweets."""
        tweets = load_fixture("mixed_batch_50.json")
        assert len(tweets) == 50

    def test_categorize_variety(self):
        """Mixed batch has multiple tweet types."""
        tweets = load_fixture("mixed_batch_50.json")
        categories = categorize_tweets(tweets)
        assert len(categories["standalone"]) > 0
        assert len(categories["threads"]) > 0
        assert len(categories["quotes"]) > 0
        assert len(categories["retweets"]) > 0
        # Note: replies with conversationId matching another tweet in the batch
        # get grouped as thread members, not isolated replies. This is correct.

    def test_thread_reconstruction(self):
        """Thread reconstruction finds multiple threads."""
        tweets = load_fixture("mixed_batch_50.json")
        threads = reconstruct_threads(tweets)
        # Should have threads and standalone tweets
        multi_tweet = [t for t in threads.values() if len(t) > 1]
        assert len(multi_tweet) >= 1  # At least the 10-tweet thread

    def test_dedupe_reduces_count(self):
        """Deduplication removes some tweets."""
        tweets = load_fixture("mixed_batch_50.json")
        deduped = dedupe_quotes(tweets)
        # Should have removed some quoted standalone tweets
        assert len(deduped) < len(tweets)

    def test_thread_stats(self):
        """Thread stats provide meaningful data."""
        tweets = load_fixture("mixed_batch_50.json")
        threads = reconstruct_threads(tweets)
        stats = get_thread_stats(threads)
        assert stats["total_threads"] > 0
        assert stats["total_tweets"] == 50
        assert stats["multi_tweet_threads"] >= 1

    def test_has_hebrew_content(self):
        """Fixture includes Hebrew content."""
        tweets = load_fixture("mixed_batch_50.json")
        hebrew_tweets = [t for t in tweets if any(ord(c) > 0x590 and ord(c) < 0x600 for c in t.text)]
        assert len(hebrew_tweets) >= 1

    def test_has_media_tweets(self):
        """Fixture includes tweets with media."""
        tweets = load_fixture("mixed_batch_50.json")
        media_tweets = [t for t in tweets if t.media]
        assert len(media_tweets) >= 3

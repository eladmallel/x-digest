"""Tests for tweet data models and parsing."""

import pytest
from x_digest.models import Tweet, Media, Author, parse_tweets, format_tweet_text, calculate_content_length, get_engagement_score
from x_digest.errors import BirdError, ErrorCode


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


def make_media(**kwargs):
    """Helper to create test media."""
    defaults = {
        "type": "photo",
        "url": "https://example.com/image.jpg",
        "width": 800,
        "height": 600,
        "preview_url": "https://example.com/thumb.jpg"
    }
    defaults.update(kwargs)
    return Media(**defaults)


def test_parse_single_tweet():
    """Parse a single tweet from JSON."""
    data = [{
        "id": "123",
        "text": "hello world",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "testuser", "name": "Test User"},
        "authorId": "1",
        "replyCount": 5,
        "retweetCount": 10,
        "likeCount": 25
    }]
    
    tweets = parse_tweets(data)
    assert len(tweets) == 1
    
    tweet = tweets[0]
    assert tweet.id == "123"
    assert tweet.text == "hello world"
    assert tweet.author.username == "testuser"
    assert tweet.author.name == "Test User"
    assert tweet.reply_count == 5
    assert tweet.retweet_count == 10
    assert tweet.like_count == 25


def test_parse_tweet_with_media():
    """Tweet with media parses correctly."""
    data = [{
        "id": "123",
        "text": "Check out this pic",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "testuser", "name": "Test User"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "media": [{
            "type": "photo",
            "url": "https://example.com/image.jpg",
            "width": 800,
            "height": 600,
            "previewUrl": "https://example.com/thumb.jpg"
        }]
    }]
    
    tweets = parse_tweets(data)
    tweet = tweets[0]
    
    assert tweet.media is not None
    assert len(tweet.media) == 1
    
    media = tweet.media[0]
    assert media.type == "photo"
    assert media.url == "https://example.com/image.jpg"
    assert media.width == 800
    assert media.height == 600
    assert media.preview_url == "https://example.com/thumb.jpg"


def test_parse_tweet_without_optional_fields():
    """Tweet without optional fields still parses."""
    data = [{
        "id": "123",
        "text": "minimal tweet",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "testuser", "name": "Test User"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0
    }]
    
    tweets = parse_tweets(data)
    tweet = tweets[0]
    
    assert tweet.media is None
    assert tweet.quoted_tweet is None
    assert tweet.in_reply_to_status_id is None


def test_parse_nested_quote_tweet():
    """Quote tweet with nested quoted content parses."""
    data = [{
        "id": "123",
        "text": "Quoting this tweet",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "quoter", "name": "Quoter"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "quotedTweet": {
            "id": "456",
            "text": "Original tweet being quoted",
            "createdAt": "Wed Feb 04 18:00:43 +0000 2026",
            "conversationId": "456",
            "author": {"username": "original", "name": "Original"},
            "authorId": "2",
            "replyCount": 0,
            "retweetCount": 0,
            "likeCount": 5
        }
    }]
    
    tweets = parse_tweets(data)
    tweet = tweets[0]
    
    assert tweet.quoted_tweet is not None
    assert tweet.quoted_tweet.id == "456"
    assert tweet.quoted_tweet.text == "Original tweet being quoted"
    assert tweet.quoted_tweet.author.username == "original"


def test_parse_invalid_json():
    """Invalid JSON raises BirdError."""
    with pytest.raises(BirdError) as exc:
        parse_tweets("invalid json")
    assert exc.value.code == ErrorCode.BIRD_JSON_PARSE_ERROR


def test_parse_non_array():
    """Non-array JSON raises BirdError."""
    with pytest.raises(BirdError) as exc:
        parse_tweets('{"not": "an array"}')
    assert exc.value.code == ErrorCode.BIRD_JSON_PARSE_ERROR


def test_format_tweet_text_simple():
    """Format simple tweet text."""
    tweet = make_tweet(text="Simple tweet")
    result = format_tweet_text(tweet)
    assert result == "Simple tweet"


def test_format_tweet_text_with_quote():
    """Format tweet text including quoted content."""
    quoted = make_tweet(id="456", text="Quoted content", author=Author(username="quoted", name="Quoted User"))
    tweet = make_tweet(text="My comment", quoted_tweet=quoted)
    
    result = format_tweet_text(tweet, include_quote=True)
    assert "My comment" in result
    assert "Quoted @quoted: Quoted content" in result


def test_format_tweet_text_no_quote():
    """Format tweet text excluding quoted content."""
    quoted = make_tweet(id="456", text="Quoted content")
    tweet = make_tweet(text="My comment", quoted_tweet=quoted)
    
    result = format_tweet_text(tweet, include_quote=False)
    assert result == "My comment"
    assert "Quoted" not in result


def test_calculate_content_length_simple():
    """Calculate length for simple tweet."""
    tweet = make_tweet(text="Hello world")
    length = calculate_content_length(tweet)
    assert length == len("Hello world")


def test_calculate_content_length_with_quote():
    """Calculate length including quoted content."""
    quoted = make_tweet(text="Quoted text")
    tweet = make_tweet(text="Main text", quoted_tweet=quoted)
    
    length = calculate_content_length(tweet)
    expected = len("Main text") + len("Quoted text")
    assert length == expected


def test_get_engagement_score():
    """Calculate engagement score with weights."""
    tweet = make_tweet(like_count=10, retweet_count=5, reply_count=3)
    score = get_engagement_score(tweet)
    
    # likes + (retweets * 2) + replies = 10 + (5 * 2) + 3 = 23
    assert score == 23


def test_parse_malformed_tweet_skipped():
    """Malformed tweets are skipped, not failed."""
    data = [
        {  # Valid tweet
            "id": "123",
            "text": "valid tweet",
            "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
            "conversationId": "123",
            "author": {"username": "test", "name": "Test"},
            "authorId": "1",
            "replyCount": 0,
            "retweetCount": 0,
            "likeCount": 0
        },
        {  # Malformed tweet (missing required fields)
            "id": "456",
            # Missing other required fields
        }
    ]
    
    tweets = parse_tweets(data)
    # Should have only the valid tweet
    assert len(tweets) == 1
    assert tweets[0].id == "123"


# Video media handling tests

def test_parse_video_media():
    """Video media parsed with duration and video URLs."""
    data = [{
        "id": "123",
        "text": "Video tweet",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "user", "name": "User"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "media": [{
            "type": "video",
            "url": "https://example.com/video.mp4",
            "previewUrl": "https://example.com/thumb.jpg",
            "videoUrl": "https://example.com/video.mp4",
            "width": 1920,
            "height": 1080,
            "durationMs": 30000
        }]
    }]
    
    tweets = parse_tweets(data)
    
    assert len(tweets) == 1
    tweet = tweets[0]
    assert len(tweet.media) == 1
    
    video = tweet.media[0]
    assert video.type == "video"
    assert video.video_url == "https://example.com/video.mp4"
    assert video.preview_url == "https://example.com/thumb.jpg"
    assert video.duration_ms == 30000


def test_parse_mixed_media():
    """Tweet with both photos and videos parsed correctly."""
    data = [{
        "id": "123",
        "text": "Mixed media tweet",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "user", "name": "User"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "media": [
            {
                "type": "photo",
                "url": "https://example.com/photo.jpg",
                "previewUrl": "https://example.com/photo_thumb.jpg",
                "width": 800,
                "height": 600
            },
            {
                "type": "video", 
                "url": "https://example.com/video.mp4",
                "previewUrl": "https://example.com/video_thumb.jpg",
                "videoUrl": "https://example.com/video.mp4",
                "width": 1920,
                "height": 1080,
                "durationMs": 45000
            }
        ]
    }]
    
    tweets = parse_tweets(data)
    tweet = tweets[0]
    assert len(tweet.media) == 2
    
    photo = tweet.media[0]
    assert photo.type == "photo"
    assert photo.video_url is None
    assert photo.duration_ms is None
    
    video = tweet.media[1]
    assert video.type == "video"
    assert video.video_url == "https://example.com/video.mp4"
    assert video.duration_ms == 45000


def test_parse_video_without_optional_fields():
    """Video media without videoUrl/durationMs handled gracefully."""
    data = [{
        "id": "123",
        "text": "Video without details",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "user", "name": "User"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0,
        "media": [{
            "type": "video",
            "url": "https://example.com/video.mp4",
            "previewUrl": "https://example.com/thumb.jpg",
            "width": 1920,
            "height": 1080
            # Missing videoUrl and durationMs
        }]
    }]
    
    tweets = parse_tweets(data)
    video = tweets[0].media[0]
    
    assert video.type == "video"
    assert video.video_url is None
    assert video.duration_ms is None
    assert video.preview_url == "https://example.com/thumb.jpg"
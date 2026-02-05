"""Tests for image handling and prioritization."""

import pytest
import base64
from unittest.mock import patch, Mock
from x_digest.models import Tweet, Media, Author
from x_digest.images import (
    prioritize_images, calculate_image_tokens, get_image_stats,
    fetch_and_encode, MAX_IMAGES, MAX_IMAGES_PER_TWEET, TOKENS_PER_IMAGE
)
from x_digest.errors import ImageError, ErrorCode


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


def test_prioritize_by_engagement():
    """Higher engagement images come first."""
    tweets = [
        make_tweet(id="1", like_count=10, retweet_count=5, media=[make_media(url="url1")]),
        make_tweet(id="2", like_count=100, retweet_count=50, media=[make_media(url="url2")]),
        make_tweet(id="3", like_count=50, retweet_count=10, media=[make_media(url="url3")]),
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    # Should be sorted by engagement: tweet2 (200), tweet3 (70), tweet1 (20)
    assert result[0] == ("2", "url2")
    assert result[1] == ("3", "url3")  
    assert result[2] == ("1", "url1")


def test_cap_per_tweet():
    """No more than max_per_tweet from one tweet."""
    media_list = [
        make_media(url=f"url{i}") for i in range(5)  # 5 images
    ]
    
    tweets = [
        make_tweet(id="1", like_count=100, media=media_list),
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    # Should have only 3 images from this tweet
    assert len(result) == 3
    assert all(tweet_id == "1" for tweet_id, url in result)


def test_cap_total():
    """No more than max_total images."""
    tweets = [
        make_tweet(id=str(i), like_count=i, media=[make_media(url=f"url{i}")])
        for i in range(20)  # 20 tweets with 1 image each
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    assert len(result) == 15
    
    # Should be top 15 by engagement (highest like counts)
    result_ids = {int(tweet_id) for tweet_id, url in result}
    expected_ids = set(range(5, 20))  # IDs 5-19 have highest like counts
    assert result_ids == expected_ids


def test_videos_use_preview():
    """Videos contribute preview URL, not video URL."""
    tweets = [
        make_tweet(id="1", media=[
            make_media(url="video_url.mp4", type="video", preview_url="thumb_url.jpg")
        ]),
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    assert len(result) == 1
    assert result[0] == ("1", "thumb_url.jpg")  # Should use preview_url


def test_mixed_photos_and_videos():
    """Mixed photos and videos handled correctly."""
    tweets = [
        make_tweet(id="1", like_count=10, media=[
            make_media(url="photo1.jpg", type="photo"),
            make_media(url="video1.mp4", type="video", preview_url="thumb1.jpg")
        ]),
        make_tweet(id="2", like_count=5, media=[
            make_media(url="photo2.jpg", type="photo"),
        ])
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    assert len(result) == 3
    
    # All from tweet 1 first (higher engagement), then tweet 2
    tweet1_results = [(tid, url) for tid, url in result if tid == "1"]
    tweet2_results = [(tid, url) for tid, url in result if tid == "2"]
    
    assert len(tweet1_results) == 2
    assert len(tweet2_results) == 1
    
    # Check video preview used
    assert ("1", "thumb1.jpg") in tweet1_results
    assert ("1", "photo1.jpg") in tweet1_results


def test_no_media_tweets():
    """Tweets without media are ignored."""
    tweets = [
        make_tweet(id="1", like_count=100),  # No media
        make_tweet(id="2", like_count=10, media=[make_media(url="url2")]),
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    assert len(result) == 1
    assert result[0] == ("2", "url2")


def test_empty_tweets_list():
    """Empty tweets list returns empty result."""
    result = prioritize_images([], max_total=15, max_per_tweet=3)
    assert result == []


def test_calculate_image_tokens():
    """Token calculation works correctly."""
    assert calculate_image_tokens(0) == 0
    assert calculate_image_tokens(1) == TOKENS_PER_IMAGE
    assert calculate_image_tokens(5) == 5 * TOKENS_PER_IMAGE
    assert calculate_image_tokens(MAX_IMAGES) == MAX_IMAGES * TOKENS_PER_IMAGE


def test_get_image_stats():
    """Image statistics are calculated correctly."""
    tweets = [
        make_tweet(id="1", media=[
            make_media(type="photo"),
            make_media(type="video")
        ]),
        make_tweet(id="2", media=[
            make_media(type="photo")
        ]),
        make_tweet(id="3"),  # No media
        make_tweet(id="4", media=[
            make_media(type="photo"),
            make_media(type="photo")
        ])
    ]
    
    stats = get_image_stats(tweets)
    
    assert stats["total_images"] == 4  # 3 photos total
    assert stats["total_videos"] == 1  # 1 video total  
    assert stats["tweets_with_media"] == 3  # 3 tweets have media
    assert stats["max_possible_images"] == MAX_IMAGES
    assert stats["estimated_tokens_if_all"] == 4 * TOKENS_PER_IMAGE


def test_engagement_score_calculation():
    """Engagement score affects prioritization correctly."""
    # Tweet with high retweets (weighted 2x) should beat high likes
    tweet_high_retweets = make_tweet(
        id="1", 
        like_count=10, 
        retweet_count=50,  # 50 * 2 = 100 points  
        reply_count=5,
        media=[make_media(url="url1")]
    )
    
    tweet_high_likes = make_tweet(
        id="2",
        like_count=90,  # 90 points
        retweet_count=0,
        reply_count=0, 
        media=[make_media(url="url2")]
    )
    
    tweets = [tweet_high_likes, tweet_high_retweets]
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    # Tweet 1 should come first due to higher weighted engagement
    # (10 + 50*2 + 5 = 115) vs (90 + 0 + 0 = 90)
    assert result[0] == ("1", "url1")
    assert result[1] == ("2", "url2")


def test_zero_engagement_handling():
    """Tweets with zero engagement are handled correctly."""
    tweets = [
        make_tweet(id="1", like_count=0, retweet_count=0, reply_count=0, 
                  media=[make_media(url="url1")]),
        make_tweet(id="2", like_count=1, retweet_count=0, reply_count=0,
                  media=[make_media(url="url2")])
    ]
    
    result = prioritize_images(tweets, max_total=15, max_per_tweet=3)
    
    assert len(result) == 2
    # Tweet 2 should come first (higher engagement)
    assert result[0] == ("2", "url2")
    assert result[1] == ("1", "url1")


# Image encoding tests (milestone 2.6)

@patch('x_digest.images.requests.get')
def test_fetch_and_encode_jpeg_image(mock_get):
    """Successfully encode JPEG image for Gemini API."""
    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "image/jpeg"}
    mock_response.content = b"fake_jpeg_data"
    mock_get.return_value = mock_response
    
    result = fetch_and_encode("https://example.com/image.jpg")
    
    assert "inline_data" in result
    assert result["inline_data"]["mime_type"] == "image/jpeg"
    assert result["inline_data"]["data"] == base64.b64encode(b"fake_jpeg_data").decode('utf-8')
    
    # Verify request was made with proper headers
    mock_get.assert_called_once_with(
        "https://example.com/image.jpg",
        timeout=10,
        headers={'User-Agent': 'x-digest/0.1.0'}
    )


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_png_image(mock_get):
    """Successfully encode PNG image."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "image/png; charset=utf-8"}
    mock_response.content = b"fake_png_data"
    mock_get.return_value = mock_response
    
    result = fetch_and_encode("https://example.com/image.png")
    
    assert result["inline_data"]["mime_type"] == "image/png"
    assert result["inline_data"]["data"] == base64.b64encode(b"fake_png_data").decode('utf-8')


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_http_404(mock_get):
    """HTTP 404 error raises ImageError."""
    mock_response = Mock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response
    
    with pytest.raises(ImageError) as exc_info:
        fetch_and_encode("https://example.com/missing.jpg")
    
    assert exc_info.value.code == ErrorCode.IMAGE_DOWNLOAD_FAILED
    assert "HTTP 404" in str(exc_info.value)


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_invalid_content_type(mock_get):
    """Non-image content type raises ImageError."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.content = b"<html>Not an image</html>"
    mock_get.return_value = mock_response
    
    with pytest.raises(ImageError) as exc_info:
        fetch_and_encode("https://example.com/notimage.html")
    
    assert exc_info.value.code == ErrorCode.IMAGE_INVALID_FORMAT
    assert "Not an image" in str(exc_info.value)


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_too_large(mock_get):
    """Image too large raises ImageError."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "image/jpeg"}
    # 15MB image (over 10MB limit)
    mock_response.content = b"x" * (15 * 1024 * 1024)
    mock_get.return_value = mock_response
    
    with pytest.raises(ImageError) as exc_info:
        fetch_and_encode("https://example.com/huge.jpg")
    
    assert exc_info.value.code == ErrorCode.IMAGE_TOO_LARGE


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_timeout(mock_get):
    """Request timeout raises ImageError."""
    import requests
    mock_get.side_effect = requests.Timeout()
    
    with pytest.raises(ImageError) as exc_info:
        fetch_and_encode("https://example.com/slow.jpg")
    
    assert exc_info.value.code == ErrorCode.IMAGE_DOWNLOAD_FAILED
    assert "Timeout" in str(exc_info.value)


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_network_error(mock_get):
    """Network error raises ImageError."""
    import requests
    mock_get.side_effect = requests.ConnectionError("Network error")
    
    with pytest.raises(ImageError) as exc_info:
        fetch_and_encode("https://example.com/image.jpg")
    
    assert exc_info.value.code == ErrorCode.IMAGE_DOWNLOAD_FAILED
    assert "Network error" in str(exc_info.value)


@patch('x_digest.images.requests.get')
def test_fetch_and_encode_missing_content_type(mock_get):
    """Missing Content-Type header defaults to image/jpeg."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.headers = {}  # No Content-Type header
    mock_response.content = b"fake_image_data"
    mock_get.return_value = mock_response
    
    result = fetch_and_encode("https://example.com/image")
    
    assert result["inline_data"]["mime_type"] == "image/jpeg"


def test_fetch_and_encode_custom_timeout():
    """Custom timeout parameter is respected."""
    with patch('x_digest.images.requests.get') as mock_get:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.content = b"data"
        mock_get.return_value = mock_response
        
        fetch_and_encode("https://example.com/image.jpg", timeout=30)
        
        mock_get.assert_called_with(
            "https://example.com/image.jpg",
            timeout=30,
            headers={'User-Agent': 'x-digest/0.1.0'}
        )
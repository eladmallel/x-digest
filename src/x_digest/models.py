"""
Data models for Twitter content.

Defines dataclasses for Tweet and Media objects that match the bird CLI output format.
Provides parsing functions to convert raw JSON data into structured Python objects.

The models handle optional fields gracefully and support the complete Twitter object
schema including threads, quotes, replies, and media attachments.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
import json

from .errors import BirdError, ErrorCode
from .utils import safe_int, safe_str


@dataclass
class Media:
    """Media attachment (photo or video) in a tweet."""
    type: str  # "photo" or "video"
    url: str  # Full-size URL
    width: int
    height: int
    preview_url: str  # Thumbnail URL
    video_url: Optional[str] = None  # For videos only
    duration_ms: Optional[int] = None  # For videos only


@dataclass
class Author:
    """Tweet author information."""
    username: str  # Handle without @, e.g. "simonw"
    name: str  # Display name, e.g. "Simon Willison"


@dataclass  
class Tweet:
    """
    A Twitter tweet with all relevant metadata.
    
    Matches the output format from bird CLI with support for threads,
    quotes, replies, and media attachments.
    """
    # Core fields (always present)
    id: str  # Tweet ID, e.g. "2019123973615939775"
    text: str  # Tweet content (may include t.co URLs)
    created_at: str  # "Wed Feb 04 19:00:43 +0000 2026"
    conversation_id: str  # Thread root ID (same as id if standalone)
    author: Author
    author_id: str  # Numeric author ID
    
    # Engagement metrics
    reply_count: int
    retweet_count: int
    like_count: int
    
    # Optional fields
    media: Optional[List[Media]] = None
    quoted_tweet: Optional['Tweet'] = None  # Forward reference
    in_reply_to_status_id: Optional[str] = None


def parse_tweets(json_data: Union[str, List[Dict[str, Any]]]) -> List[Tweet]:
    """
    Parse tweets from bird CLI JSON output.
    
    Args:
        json_data: Raw JSON string or parsed list of tweet dictionaries
        
    Returns:
        List of Tweet objects
        
    Raises:
        BirdError: If JSON parsing fails or data format is invalid
    """
    if isinstance(json_data, str):
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            raise BirdError(
                ErrorCode.BIRD_JSON_PARSE_ERROR,
                f"Invalid JSON: {str(e)}"
            )
    else:
        data = json_data
    
    if not isinstance(data, list):
        raise BirdError(
            ErrorCode.BIRD_JSON_PARSE_ERROR,
            "Expected JSON array of tweets"
        )
    
    tweets = []
    for tweet_data in data:
        try:
            tweet = _parse_single_tweet(tweet_data)
            tweets.append(tweet)
        except (KeyError, TypeError, ValueError) as e:
            # Skip malformed tweets but continue processing
            # This handles cases where bird CLI returns partial data
            continue
    
    return tweets


def _parse_single_tweet(data: Dict[str, Any]) -> Tweet:
    """Parse a single tweet from JSON data."""
    # Validate required fields exist and are non-empty
    required_fields = ["id", "text", "author"]
    for field in required_fields:
        if field not in data or data[field] is None:
            raise KeyError(f"Missing required field: {field}")
    
    # Validate author has required subfields
    if not isinstance(data["author"], dict) or "username" not in data["author"]:
        raise ValueError("Invalid author data: missing username")
    
    # Parse author
    author_data = data.get("author", {})
    author = Author(
        username=safe_str(author_data.get("username"), "unknown"),
        name=safe_str(author_data.get("name"), "Unknown User")
    )
    
    # Parse media if present
    media = None
    if "media" in data and data["media"]:
        media = []
        for media_data in data["media"]:
            media_obj = Media(
                type=safe_str(media_data.get("type"), "photo"),
                url=safe_str(media_data.get("url"), ""),
                width=safe_int(media_data.get("width"), 0),
                height=safe_int(media_data.get("height"), 0),
                preview_url=safe_str(media_data.get("previewUrl", media_data.get("url", "")), ""),
                video_url=safe_str(media_data.get("videoUrl")) if media_data.get("videoUrl") else None,
                duration_ms=safe_int(media_data.get("durationMs")) if media_data.get("durationMs") else None
            )
            media.append(media_obj)
    
    # Parse quoted tweet if present (recursive)
    quoted_tweet = None
    if "quotedTweet" in data and data["quotedTweet"]:
        quoted_tweet = _parse_single_tweet(data["quotedTweet"])
    
    # Create main tweet object
    tweet = Tweet(
        id=safe_str(data["id"]),
        text=safe_str(data.get("text"), ""),
        created_at=safe_str(data.get("createdAt"), ""),
        conversation_id=safe_str(data.get("conversationId", data["id"])),
        author=author,
        author_id=safe_str(data.get("authorId"), "0"),
        reply_count=safe_int(data.get("replyCount"), 0),
        retweet_count=safe_int(data.get("retweetCount"), 0),
        like_count=safe_int(data.get("likeCount"), 0),
        media=media,
        quoted_tweet=quoted_tweet,
        in_reply_to_status_id=safe_str(data["inReplyToStatusId"]) if data.get("inReplyToStatusId") else None
    )
    
    return tweet


def format_tweet_text(tweet: Tweet, include_quote: bool = True) -> str:
    """
    Format tweet text for display, optionally including quoted content.
    
    Args:
        tweet: Tweet object
        include_quote: Whether to append quoted tweet content
        
    Returns:
        Formatted text string
    """
    text = tweet.text
    
    if include_quote and tweet.quoted_tweet:
        quoted = tweet.quoted_tweet
        quote_text = f"\n\nQuoted @{quoted.author.username}: {quoted.text}"
        text += quote_text
    
    return text


def calculate_content_length(tweet: Tweet) -> int:
    """
    Calculate total character length including quoted content.
    
    Used for pre-summarization threshold checks.
    """
    length = len(tweet.text)
    
    if tweet.quoted_tweet:
        length += len(tweet.quoted_tweet.text)
    
    return length


def get_engagement_score(tweet: Tweet) -> int:
    """
    Calculate engagement score for prioritization.
    
    Weights retweets higher than likes as they indicate stronger signal.
    """
    return tweet.like_count + (tweet.retweet_count * 2) + tweet.reply_count
"""
Image handling for multimodal digest generation.

Handles image prioritization, downloading, and encoding for LLM consumption.
Implements engagement-based sorting with per-tweet caps to ensure variety
across tweets while respecting token budget constraints.
"""

import requests
import base64
from typing import Any, List, Dict, Tuple, Optional, TYPE_CHECKING
from dataclasses import dataclass

from .models import Tweet, Media, get_engagement_score
from .errors import ImageError, ErrorCode

if TYPE_CHECKING:
    from .llm.base import LLMProvider


# Image handling constants
TOKENS_PER_IMAGE = 1900  # Tested with Gemini 2.0 Flash
MAX_IMAGE_TOKENS = 30000  # Token budget for images
MAX_IMAGES = MAX_IMAGE_TOKENS // TOKENS_PER_IMAGE  # ~15
MAX_IMAGES_PER_TWEET = 3  # Ensure variety across tweets


@dataclass
class PrioritizedImage:
    """Image with prioritization metadata."""
    tweet_id: str
    url: str
    type: str  # "photo" or "video"
    engagement: int
    is_video_preview: bool = False


def prioritize_images(tweets: List[Tweet], max_total: int = MAX_IMAGES, max_per_tweet: int = MAX_IMAGES_PER_TWEET) -> List[Tuple[str, str]]:
    """
    Select which images to include in digest based on engagement.
    
    Args:
        tweets: List of tweets to extract images from
        max_total: Maximum total images to include
        max_per_tweet: Maximum images per individual tweet
        
    Returns:
        List of (tweet_id, image_url) tuples, sorted by engagement
        
    Logic:
    1. Extract up to max_per_tweet images from each tweet
    2. Sort by engagement (likes + 2*retweets + replies)
    3. Take top max_total images globally
    4. For videos, use preview URL instead of video URL
    """
    prioritized_images = []
    
    for tweet in tweets:
        if not tweet.media:
            continue
        
        engagement = get_engagement_score(tweet)
        
        # Extract images/videos from this tweet, up to the per-tweet limit
        tweet_images = []
        for media in tweet.media:
            if media.type == "photo":
                tweet_images.append(PrioritizedImage(
                    tweet_id=tweet.id,
                    url=media.url,
                    type=media.type,
                    engagement=engagement
                ))
            elif media.type == "video":
                # Use preview/thumbnail for videos
                tweet_images.append(PrioritizedImage(
                    tweet_id=tweet.id,
                    url=media.preview_url,
                    type=media.type,
                    engagement=engagement,
                    is_video_preview=True
                ))
        
        # Sort by engagement and take up to max_per_tweet
        tweet_images.sort(key=lambda x: x.engagement, reverse=True)
        prioritized_images.extend(tweet_images[:max_per_tweet])
    
    # Sort all images by engagement and take top max_total
    prioritized_images.sort(key=lambda x: x.engagement, reverse=True)
    selected_images = prioritized_images[:max_total]
    
    # Return as (tweet_id, url) tuples
    return [(img.tweet_id, img.url) for img in selected_images]


def fetch_and_encode(url: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Download image and encode for Gemini API.
    
    Args:
        url: Image URL to download
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary with Gemini inline_data structure:
        {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": "base64_encoded_data"
            }
        }
        
    Raises:
        ImageError: If download fails or encoding fails
    """
    try:
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'x-digest/0.1.0'
        })
        
        if response.status_code != 200:
            raise ImageError(
                ErrorCode.IMAGE_DOWNLOAD_FAILED,
                f"HTTP {response.status_code} for {url}"
            )
        
        # Detect MIME type from response headers
        content_type = response.headers.get("Content-Type", "image/jpeg")
        mime_type = content_type.split(";")[0].strip()  # Strip charset if present
        
        # Validate it's actually an image
        if not mime_type.startswith("image/"):
            raise ImageError(
                ErrorCode.IMAGE_INVALID_FORMAT,
                f"Not an image: {mime_type}"
            )
        
        # Check file size (rough limit: 10MB)
        if len(response.content) > 10 * 1024 * 1024:
            raise ImageError(
                ErrorCode.IMAGE_TOO_LARGE,
                f"Image too large: {len(response.content)} bytes"
            )
        
        # Encode to base64
        try:
            img_base64 = base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            raise ImageError(
                ErrorCode.IMAGE_ENCODING_FAILED,
                f"Base64 encoding failed: {str(e)}"
            )
        
        return {
            "inline_data": {
                "mime_type": mime_type,
                "data": img_base64
            }
        }
        
    except requests.Timeout:
        raise ImageError(ErrorCode.IMAGE_DOWNLOAD_FAILED, f"Timeout downloading {url}")
    except requests.RequestException as e:
        raise ImageError(ErrorCode.IMAGE_DOWNLOAD_FAILED, f"Network error: {str(e)}")


def describe_overflow_images(image_urls: List[str], llm_provider: 'LLMProvider') -> List[str]:
    """
    Generate text descriptions for images that exceed the token budget.
    
    Args:
        image_urls: URLs of images to describe
        llm_provider: LLM provider for image description
        
    Returns:
        List of text descriptions
        
    This is used when we have more images than fit in the token budget.
    The descriptions are included in the digest payload as "[Image: description]"
    """
    descriptions = []
    
    for url in image_urls:
        try:
            # Download and encode image
            encoded_image = fetch_and_encode(url)
            
            # Generate description
            prompt = "Describe this image in 1-2 sentences. Focus on the key visual information."
            description = llm_provider.generate(prompt, images=[encoded_image])
            descriptions.append(description.strip())
            
        except (ImageError, Exception):
            # Fallback if description fails
            descriptions.append("Image unavailable")
    
    return descriptions


def calculate_image_tokens(num_images: int) -> int:
    """Calculate estimated token usage for a number of images."""
    return num_images * TOKENS_PER_IMAGE


def get_image_stats(tweets: List[Tweet]) -> Dict[str, int]:
    """
    Get statistics about images in tweet batch.
    
    Returns:
        Dictionary with image counts and metrics
    """
    total_images = 0
    total_videos = 0
    tweets_with_media = 0
    
    for tweet in tweets:
        if tweet.media:
            tweets_with_media += 1
            for media in tweet.media:
                if media.type == "photo":
                    total_images += 1
                elif media.type == "video":
                    total_videos += 1
    
    return {
        "total_images": total_images,
        "total_videos": total_videos,
        "tweets_with_media": tweets_with_media,
        "max_possible_images": MAX_IMAGES,
        "estimated_tokens_if_all": calculate_image_tokens(total_images)
    }
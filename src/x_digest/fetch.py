"""
Twitter data fetching using bird CLI.

Integrates with the bird CLI to fetch tweets from Twitter lists.
Handles authentication, rate limiting, error mapping, and JSON parsing.

The fetch module abstracts the bird CLI interface and provides structured
error handling with proper error code mapping for monitoring.
"""

from typing import List, Optional
from datetime import datetime

from .models import Tweet, parse_tweets
from .errors import BirdError, ErrorCode


def fetch_tweets_from_bird(
    list_id: str,
    since: datetime,
    env_path: Optional[str] = None
) -> List[Tweet]:
    """
    Fetch tweets from Twitter list using bird CLI.
    
    Args:
        list_id: Twitter list ID
        since: Fetch tweets since this timestamp
        env_path: Path to bird environment file
        
    Returns:
        List of Tweet objects
        
    Raises:
        BirdError: If bird CLI fails or returns invalid data
    """
    # TODO: Implementation in Phase 5 (external integration)
    # For now, return empty list for testing purposes
    return []


def check_bird_auth(env_path: Optional[str] = None) -> bool:
    """
    Check if bird CLI authentication is working.
    
    Args:
        env_path: Path to bird environment file
        
    Returns:
        True if authentication works, False otherwise
    """
    # TODO: Implementation in Phase 5
    # For now, return False indicating auth not available
    return False
"""
Utility functions shared across x-digest modules.

Provides common functionality like date parsing, validation helpers,
and other utility functions to reduce code duplication.
"""

from datetime import datetime, UTC
from typing import Optional


def parse_twitter_date(date_str: str) -> datetime:
    """
    Parse Twitter date format to datetime object.
    
    Handles multiple formats:
    - Twitter format: "Wed Feb 04 19:00:43 +0000 2026"
    - ISO format: "2026-02-04T19:00:43Z"
    - ISO with timezone: "2026-02-04T19:00:43+00:00"
    
    Args:
        date_str: Date string to parse
        
    Returns:
        Parsed datetime object in UTC
        
    Fallback to epoch (1970-01-01) if parsing fails completely.
    """
    try:
        # Twitter format: "Wed Feb 04 19:00:43 +0000 2026"
        if "+0000" in date_str:
            date_part = date_str.replace("+0000", "").strip()
            dt = datetime.strptime(date_part, "%a %b %d %H:%M:%S %Y")
            return dt.replace(tzinfo=UTC)
        
        # ISO format with Z
        if date_str.endswith('Z'):
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        # ISO format with timezone
        if '+' in date_str or date_str.count('-') > 2:
            return datetime.fromisoformat(date_str)
        
        # Fallback - assume it's a simple format
        return datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        
    except (ValueError, TypeError):
        # If all else fails, return epoch
        return datetime.fromtimestamp(0, tz=UTC)


def format_relative_time(date_str: str, now: Optional[datetime] = None) -> str:
    """
    Format timestamp as relative time (e.g., "2h ago", "1d ago").
    
    Args:
        date_str: Date string to format
        now: Current time (defaults to UTC now)
        
    Returns:
        Human-readable relative time string
    """
    if now is None:
        now = datetime.now(UTC)
    
    try:
        tweet_time = parse_twitter_date(date_str)
        # Handle invalid dates (epoch time)
        if tweet_time.year == 1970:
            return "recently"
            
        diff = now - tweet_time
        seconds = int(diff.total_seconds())
        
        if seconds < 0:  # Future date
            return "recently"
        elif seconds < 60:
            return "now"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        else:
            days = seconds // 86400
            return f"{days}d ago"
            
    except Exception:
        return "recently"


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text to maximum length with suffix.
    
    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text with suffix if needed
    """
    if len(text) <= max_length:
        return text
    
    # If suffix is longer than max_length, return truncated suffix
    if len(suffix) >= max_length:
        return suffix[:max_length]
    
    # Account for suffix length
    actual_max = max_length - len(suffix)
    return text[:actual_max] + suffix


def safe_int(value, default: int = 0) -> int:
    """
    Safely convert value to integer with default fallback.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
        
    Returns:
        Integer value or default
    """
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def safe_str(value, default: str = "") -> str:
    """
    Safely convert value to string with default fallback.
    
    Args:
        value: Value to convert 
        default: Default value if conversion fails
        
    Returns:
        String value or default
    """
    try:
        return str(value) if value is not None else default
    except Exception:
        return default
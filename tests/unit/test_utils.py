"""Tests for utility functions."""

import pytest
from datetime import datetime, UTC, timedelta
from x_digest.utils import (
    parse_twitter_date, format_relative_time, truncate_text,
    safe_int, safe_str
)


def test_parse_twitter_date_standard_format():
    """Parse standard Twitter date format."""
    date_str = "Wed Feb 04 19:00:43 +0000 2026"
    result = parse_twitter_date(date_str)
    
    assert result.year == 2026
    assert result.month == 2
    assert result.day == 4
    assert result.hour == 19
    assert result.tzinfo == UTC


def test_parse_twitter_date_iso_format():
    """Parse ISO date format."""
    date_str = "2026-02-04T19:00:43Z"
    result = parse_twitter_date(date_str)
    
    assert result.year == 2026
    assert result.month == 2
    assert result.day == 4
    assert result.hour == 19
    assert result.tzinfo == UTC


def test_parse_twitter_date_iso_with_timezone():
    """Parse ISO date format with timezone."""
    date_str = "2026-02-04T19:00:43+00:00"
    result = parse_twitter_date(date_str)
    
    assert result.year == 2026
    assert result.month == 2
    assert result.day == 4
    assert result.hour == 19


def test_parse_twitter_date_invalid_format():
    """Invalid date format returns epoch."""
    result = parse_twitter_date("invalid date")
    assert result.year == 1970


def test_format_relative_time_minutes():
    """Format time that's minutes ago."""
    now = datetime(2026, 2, 4, 19, 30, tzinfo=UTC)
    date_str = "Wed Feb 04 19:15:00 +0000 2026"
    
    result = format_relative_time(date_str, now)
    assert result == "15m ago"


def test_format_relative_time_hours():
    """Format time that's hours ago."""
    now = datetime(2026, 2, 4, 21, 0, tzinfo=UTC)
    date_str = "Wed Feb 04 19:00:00 +0000 2026"
    
    result = format_relative_time(date_str, now)
    assert result == "2h ago"


def test_format_relative_time_days():
    """Format time that's days ago."""
    now = datetime(2026, 2, 6, 19, 0, tzinfo=UTC)
    date_str = "Wed Feb 04 19:00:00 +0000 2026"
    
    result = format_relative_time(date_str, now)
    assert result == "2d ago"


def test_format_relative_time_now():
    """Format time that's very recent."""
    now = datetime(2026, 2, 4, 19, 0, 30, tzinfo=UTC)
    date_str = "Wed Feb 04 19:00:00 +0000 2026"
    
    result = format_relative_time(date_str, now)
    assert result == "now"


def test_format_relative_time_invalid():
    """Invalid date returns 'recently'."""
    result = format_relative_time("invalid date")
    assert result == "recently"


def test_truncate_text_no_truncation():
    """Short text is not truncated."""
    text = "Short text"
    result = truncate_text(text, 20)
    assert result == "Short text"


def test_truncate_text_with_suffix():
    """Long text is truncated with suffix."""
    text = "This is a very long text that needs truncation"
    result = truncate_text(text, 20, "...")
    assert len(result) == 20
    assert result.endswith("...")
    assert result == "This is a very lo..."


def test_truncate_text_custom_suffix():
    """Truncation with custom suffix."""
    text = "Long text here"
    result = truncate_text(text, 10, " [more]")
    assert len(result) == 10
    assert result.endswith(" [more]")


def test_truncate_text_suffix_longer_than_max():
    """Suffix longer than max length."""
    text = "Text"
    result = truncate_text(text, 5, "very long suffix")
    assert result == "Text"  # Text fits in 5 chars, no truncation needed


def test_safe_int_valid():
    """Valid integer conversion."""
    assert safe_int("123") == 123
    assert safe_int(456) == 456
    assert safe_int("0") == 0


def test_safe_int_invalid():
    """Invalid values return default."""
    assert safe_int("not a number") == 0
    assert safe_int(None) == 0
    assert safe_int("") == 0
    assert safe_int([]) == 0


def test_safe_int_custom_default():
    """Invalid values return custom default."""
    assert safe_int("invalid", default=42) == 42
    assert safe_int(None, default=-1) == -1


def test_safe_str_valid():
    """Valid string conversion."""
    assert safe_str("hello") == "hello"
    assert safe_str(123) == "123"
    assert safe_str(True) == "True"


def test_safe_str_invalid():
    """Invalid values return default."""
    assert safe_str(None) == ""


def test_safe_str_custom_default():
    """Invalid values return custom default."""
    assert safe_str(None, default="N/A") == "N/A"
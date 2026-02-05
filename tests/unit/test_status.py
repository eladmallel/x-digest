"""Tests for status file management."""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, UTC, timedelta
from pathlib import Path
import pytest

from x_digest.status import (
    load_status, update_status, should_run, get_time_window, 
    write_meta, _create_default_status
)
from x_digest.errors import StatusError, ErrorCode


def test_load_creates_if_missing(tmp_path):
    """Loading non-existent status creates empty structure."""
    status_file = tmp_path / "status.json"
    status = load_status(str(status_file))
    
    # Should have default structure
    assert status["lists"] == {}
    assert status["cookie_status"] == "unknown"
    assert "created_at" in status
    assert "last_updated" in status


def test_load_existing_status(tmp_path):
    """Loading existing status file works."""
    status_file = tmp_path / "status.json"
    
    # Create existing status file
    existing_data = {
        "lists": {"test-list": {"last_run": "2026-02-04T12:00:00Z"}},
        "cookie_status": "valid",
        "created_at": "2026-02-01T00:00:00Z",
        "last_updated": "2026-02-04T12:00:00Z"
    }
    status_file.write_text(json.dumps(existing_data))
    
    status = load_status(str(status_file))
    assert status["lists"]["test-list"]["last_run"] == "2026-02-04T12:00:00Z"
    assert status["cookie_status"] == "valid"


def test_update_status_creates_list_entry(tmp_path):
    """Updating unknown list creates entry."""
    status_file = tmp_path / "status.json"
    
    update_status(str(status_file), "ai-dev", last_run="2026-01-01T00:00:00Z")
    
    status = load_status(str(status_file))
    assert "ai-dev" in status["lists"]
    assert status["lists"]["ai-dev"]["last_run"] == "2026-01-01T00:00:00Z"
    assert status["lists"]["ai-dev"]["tweets_fetched"] == 0  # Default value


def test_update_status_preserves_other_fields(tmp_path):
    """Updating one field doesn't clobber others."""
    status_file = tmp_path / "status.json"
    
    # First update
    update_status(str(status_file), "ai-dev", 
                 last_run="2026-01-01T00:00:00Z", 
                 error_code=None)
    
    # Second update with different field
    update_status(str(status_file), "ai-dev", tweets_fetched=50)
    
    status = load_status(str(status_file))
    ai_dev = status["lists"]["ai-dev"]
    
    # Both fields should be present
    assert ai_dev["last_run"] == "2026-01-01T00:00:00Z"
    assert ai_dev["tweets_fetched"] == 50
    assert ai_dev["error_code"] is None


def test_concurrent_updates_dont_corrupt(tmp_path):
    """Simulated concurrent updates don't corrupt file."""
    status_file = tmp_path / "status.json"
    
    def updater(list_name, n):
        for i in range(5):  # Reduced iterations for faster test
            update_status(str(status_file), list_name, counter=i)
            time.sleep(0.01)  # Small delay to increase chance of collision
    
    # Run concurrent updates
    threads = [
        threading.Thread(target=updater, args=("list-a", 5)),
        threading.Thread(target=updater, args=("list-b", 5)),
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Verify file is not corrupted and both lists exist
    status = load_status(str(status_file))
    assert "list-a" in status["lists"]
    assert "list-b" in status["lists"]
    assert isinstance(status["lists"]["list-a"]["counter"], int)
    assert isinstance(status["lists"]["list-b"]["counter"], int)


def test_should_run_first_time():
    """First run always allowed."""
    status = {"lists": {}}
    assert should_run("ai-dev", status) is True


def test_should_run_after_window():
    """Run allowed after window expires."""
    # 60 minutes ago
    old_time = (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    status = {"lists": {"ai-dev": {"last_run": old_time}}}
    
    # Should allow run with 30 minute window
    assert should_run("ai-dev", status, window_minutes=30) is True


def test_should_not_run_within_window():
    """Run blocked within window."""
    # 10 minutes ago  
    recent_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    status = {"lists": {"ai-dev": {"last_run": recent_time}}}
    
    # Should block run with 30 minute window
    assert should_run("ai-dev", status, window_minutes=30) is False


def test_should_run_invalid_timestamp():
    """Invalid timestamp allows run."""
    status = {"lists": {"ai-dev": {"last_run": "invalid-timestamp"}}}
    assert should_run("ai-dev", status) is True


def test_get_time_window_from_last_success():
    """Window starts from last success."""
    last_success = "2026-02-04T10:00:00Z"
    status = {"lists": {"ai-dev": {"last_success": last_success}}}
    
    start, end = get_time_window("ai-dev", status)
    
    expected_start = datetime.fromisoformat(last_success.replace('Z', '+00:00'))
    assert start == expected_start
    
    # End should be approximately now
    now = datetime.now(UTC)
    assert abs((end - now).total_seconds()) < 5


def test_get_time_window_default_24h():
    """Default to 24h lookback."""
    status = {"lists": {}}
    
    start, end = get_time_window("ai-dev", status)
    
    # Should be approximately 24 hours apart
    diff = end - start
    assert 23 <= diff.total_seconds() / 3600 <= 25  # ~24 hours ±1 hour


def test_get_time_window_end_is_now():
    """End time is approximately now."""
    status = {"lists": {}}
    
    _, end = get_time_window("ai-dev", status)
    
    now = datetime.now(UTC)
    assert abs((end - now).total_seconds()) < 5  # Within 5 seconds


def test_write_meta_creates_directory(tmp_path):
    """Meta file creates nested directory structure."""
    metrics = {
        "timestamp": "2026-02-04T12:00:00Z",
        "list": "ai-dev",
        "success": True,
        "tweets": {"fetched": 25}
    }
    
    write_meta(str(tmp_path), metrics)
    
    # Should create: data/digests/2026/02/week-06/2026-02-04/ai-dev/meta.json
    expected = tmp_path / "digests" / "2026" / "02" / "week-06" / "2026-02-04" / "ai-dev" / "meta.json"
    assert expected.exists()


def test_write_meta_contains_all_fields(tmp_path):
    """Meta file contains required fields."""
    metrics = {
        "timestamp": "2026-02-04T12:00:00Z",
        "list": "ai-dev", 
        "success": True,
        "tweets": {"fetched": 50},
        "tokens": {"total_in": 10000},
    }
    
    write_meta(str(tmp_path), metrics)
    
    # Find and read the meta file
    meta_files = list((tmp_path / "digests").rglob("meta.json"))
    assert len(meta_files) == 1
    
    with open(meta_files[0]) as f:
        data = json.load(f)
    
    assert data["list"] == "ai-dev"
    assert data["success"] is True
    assert data["tweets"]["fetched"] == 50
    assert data["tokens"]["total_in"] == 10000


def test_write_meta_auto_timestamp(tmp_path):
    """Meta adds timestamp if missing."""
    metrics = {"list": "test", "success": True}
    
    write_meta(str(tmp_path), metrics)
    
    meta_files = list((tmp_path / "digests").rglob("meta.json"))
    with open(meta_files[0]) as f:
        data = json.load(f)
    
    assert "timestamp" in data
    # Should be a valid ISO timestamp
    datetime.fromisoformat(data["timestamp"].replace('Z', '+00:00'))


def test_update_status_with_none_values(tmp_path):
    """Status update handles None values correctly."""
    status_file = tmp_path / "status.json"
    
    update_status(str(status_file), "test-list", 
                 error_code=None, 
                 last_success=None,
                 tweets_fetched=0)
    
    status = load_status(str(status_file))
    list_status = status["lists"]["test-list"]
    
    assert list_status["error_code"] is None
    assert list_status["last_success"] is None
    assert list_status["tweets_fetched"] == 0


def test_status_file_corruption_recovery(tmp_path):
    """Corrupted status file is recovered gracefully."""
    status_file = tmp_path / "status.json"
    
    # Write corrupted JSON
    status_file.write_text("{ corrupted json")
    
    # Should recover by creating new status
    update_status(str(status_file), "test", last_run="2026-02-04T12:00:00Z")
    
    status = load_status(str(status_file))
    assert status["lists"]["test"]["last_run"] == "2026-02-04T12:00:00Z"
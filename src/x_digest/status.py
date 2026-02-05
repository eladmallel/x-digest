"""
Status file management for x-digest.

Handles reading and writing the status.json file with proper file locking
to prevent race conditions when multiple digest processes run concurrently.

The status file tracks run metadata, error states, and timestamps for each
list to enable monitoring and prevent duplicate runs.
"""

import json
import os
import fcntl
import time
from datetime import datetime, timedelta, UTC
from typing import Dict, Any, Optional
from pathlib import Path

from .errors import StatusError, ErrorCode


def load_status(status_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load status file with default structure if missing.
    
    Args:
        status_path: Path to status file. If None, uses default location.
        
    Returns:
        Status dictionary with default structure if file doesn't exist
        
    Raises:
        StatusError: If file exists but is corrupted or locked
    """
    if status_path is None:
        status_path = _get_default_status_path()
    
    # Create parent directory if it doesn't exist
    Path(status_path).parent.mkdir(parents=True, exist_ok=True)
    
    # If file doesn't exist, return default structure
    if not os.path.exists(status_path):
        return _create_default_status()
    
    try:
        with open(status_path, 'r', encoding='utf-8') as f:
            # Use shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                status = json.load(f)
                return _validate_status_structure(status)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError:
        raise StatusError(ErrorCode.STATUS_FILE_CORRUPT)
    except BlockingIOError:
        raise StatusError(ErrorCode.STATUS_FILE_LOCKED)
    except PermissionError:
        raise StatusError(ErrorCode.WRITE_PERMISSION_DENIED)


def update_status(status_path: Optional[str], list_name: str, **kwargs) -> None:
    """
    Update status for a specific list with file locking.
    
    Args:
        status_path: Path to status file. If None, uses default location.
        list_name: Name of the list to update
        **kwargs: Status fields to update (last_run, last_success, error_code, etc.)
        
    Raises:
        StatusError: If file cannot be locked or written
    """
    if status_path is None:
        status_path = _get_default_status_path()
    
    # Ensure parent directory exists
    Path(status_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Lock file for exclusive access
    try:
        # Open in read-write mode, create if doesn't exist
        with open(status_path, 'r+' if os.path.exists(status_path) else 'w+', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                # Load existing status or create new
                f.seek(0)
                content = f.read().strip()
                if not content:
                    status = _create_default_status()
                else:
                    try:
                        status = json.loads(content)
                    except json.JSONDecodeError:
                        # Corrupted file, start fresh
                        status = _create_default_status()
                
                # Ensure lists section exists
                if "lists" not in status:
                    status["lists"] = {}
                
                # Initialize list entry if it doesn't exist
                if list_name not in status["lists"]:
                    status["lists"][list_name] = _create_default_list_entry()
                
                # Update fields
                for key, value in kwargs.items():
                    status["lists"][list_name][key] = value
                
                # Update last_updated timestamp
                status["last_updated"] = datetime.now(UTC).isoformat()
                
                # Write back to file
                f.seek(0)
                f.truncate()
                json.dump(status, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
                
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                
    except BlockingIOError:
        raise StatusError(ErrorCode.STATUS_FILE_LOCKED)
    except PermissionError:
        raise StatusError(ErrorCode.WRITE_PERMISSION_DENIED)


def should_run(list_name: str, status: Dict[str, Any], window_minutes: int = 30) -> bool:
    """
    Check if digest should run based on last run timestamp.
    
    Args:
        list_name: Name of the list
        status: Status dictionary (from load_status)
        window_minutes: Idempotency window in minutes
        
    Returns:
        True if digest should run, False if within idempotency window
    """
    if "lists" not in status or list_name not in status["lists"]:
        return True  # First run
    
    list_status = status["lists"][list_name]
    last_run = list_status.get("last_run")
    
    if not last_run:
        return True  # Never run before
    
    try:
        last_run_time = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
        now = datetime.now(UTC)
        elapsed = now - last_run_time
        
        return elapsed.total_seconds() > (window_minutes * 60)
    except (ValueError, AttributeError):
        # Invalid timestamp, allow run
        return True


def get_time_window(list_name: str, status: Dict[str, Any]) -> tuple[datetime, datetime]:
    """
    Calculate time window for fetching tweets.
    
    Args:
        list_name: Name of the list
        status: Status dictionary
        
    Returns:
        Tuple of (start_time, end_time) for fetching tweets
        
    Logic:
    - If last_success exists, start from that time
    - Otherwise, default to 24 hours ago
    - End time is always now
    """
    end_time = datetime.now(UTC)
    
    if "lists" not in status or list_name not in status["lists"]:
        # First run: default to 24 hours
        start_time = end_time - timedelta(hours=24)
        return start_time, end_time
    
    list_status = status["lists"][list_name]
    last_success = list_status.get("last_success")
    
    if last_success:
        try:
            start_time = datetime.fromisoformat(last_success.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            # Invalid timestamp, fall back to 24 hours
            start_time = end_time - timedelta(hours=24)
    else:
        # No previous success, default to 24 hours
        start_time = end_time - timedelta(hours=24)
    
    return start_time, end_time


def write_meta(data_dir: str, metrics: Dict[str, Any]) -> None:
    """
    Write run metadata to organized file structure.
    
    Args:
        data_dir: Base data directory
        metrics: Run metadata dictionary
        
    Creates directory structure: year/month/week/day/list/meta.json
    """
    timestamp = metrics.get("timestamp")
    if not timestamp:
        timestamp = datetime.now(UTC).isoformat()
        metrics["timestamp"] = timestamp
    
    # Parse timestamp
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        dt = datetime.now(UTC)
    
    # Build path: data/digests/2026/02/week-05/2026-02-04/ai-dev/meta.json
    year = dt.strftime("%Y")
    month = dt.strftime("%m") 
    week = f"week-{dt.isocalendar()[1]:02d}"
    day = dt.strftime("%Y-%m-%d")
    list_name = metrics.get("list", "unknown")
    
    meta_dir = Path(data_dir) / "digests" / year / month / week / day / list_name
    meta_dir.mkdir(parents=True, exist_ok=True)
    
    meta_file = meta_dir / "meta.json"
    
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)


def _get_default_status_path() -> str:
    """Get default status file path."""
    return os.path.join(os.getcwd(), "data", "status.json")


def _create_default_status() -> Dict[str, Any]:
    """Create default status file structure."""
    return {
        "lists": {},
        "cookie_status": "unknown",
        "created_at": datetime.now(UTC).isoformat(),
        "last_updated": datetime.now(UTC).isoformat()
    }


def _create_default_list_entry() -> Dict[str, Any]:
    """Create default status entry for a new list."""
    return {
        "last_run": None,
        "last_success": None,
        "error_code": None,
        "tweets_fetched": 0,
        "tweets_processed": 0,
        "digest_sent": False,
        "run_count": 0
    }


def _validate_status_structure(status: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and fix status file structure.
    
    Ensures required fields exist and have correct types.
    """
    if not isinstance(status, dict):
        return _create_default_status()
    
    # Ensure required top-level fields
    if "lists" not in status or not isinstance(status["lists"], dict):
        status["lists"] = {}
    
    if "cookie_status" not in status:
        status["cookie_status"] = "unknown"
    
    if "last_updated" not in status:
        status["last_updated"] = datetime.now(UTC).isoformat()
    
    # Validate list entries
    for list_name, list_status in status["lists"].items():
        if not isinstance(list_status, dict):
            status["lists"][list_name] = _create_default_list_entry()
            continue
        
        # Ensure required list fields exist
        defaults = _create_default_list_entry()
        for key, default_value in defaults.items():
            if key not in list_status:
                list_status[key] = default_value
    
    return status
"""
Logging configuration for x-digest.

Provides a rotating file logger with configurable log level and structured
log format with timestamps. Supports configuration via config file or
environment variable (LOG_LEVEL).

Log file defaults to data/x-digest.log with 5MB max size and 3 backups.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any


# Module-level logger
_logger: Optional[logging.Logger] = None

# Defaults
DEFAULT_LOG_FILE = "data/x-digest.log"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5MB
DEFAULT_BACKUP_COUNT = 3
DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def setup_logging(
    config: Optional[Dict[str, Any]] = None,
    log_file: Optional[str] = None,
    log_level: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
) -> logging.Logger:
    """
    Configure and return the x-digest logger.

    Precedence for log level:
    1. Explicit log_level parameter
    2. LOG_LEVEL environment variable
    3. Config file setting (config["logging"]["level"])
    4. Default: INFO

    Precedence for log file:
    1. Explicit log_file parameter
    2. Config file setting (config["logging"]["file"])
    3. Default: data/x-digest.log

    Args:
        config: Configuration dictionary (optional)
        log_file: Override log file path
        log_level: Override log level
        max_bytes: Override max file size in bytes
        backup_count: Override number of backup files

    Returns:
        Configured logging.Logger instance
    """
    global _logger

    logging_config = {}
    if config:
        logging_config = config.get("logging", {})

    # Resolve log level
    resolved_level = (
        log_level
        or os.environ.get("LOG_LEVEL")
        or logging_config.get("level")
        or DEFAULT_LOG_LEVEL
    ).upper()

    # Validate log level
    numeric_level = getattr(logging, resolved_level, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
        resolved_level = "INFO"

    # Resolve log file path
    resolved_file = (
        log_file
        or logging_config.get("file")
        or DEFAULT_LOG_FILE
    )

    # Resolve rotation settings
    resolved_max_bytes = (
        max_bytes
        or logging_config.get("max_bytes")
        or DEFAULT_MAX_BYTES
    )

    resolved_backup_count = (
        backup_count
        if backup_count is not None
        else logging_config.get("backup_count", DEFAULT_BACKUP_COUNT)
    )

    # Create logger
    logger = logging.getLogger("x_digest")
    logger.setLevel(numeric_level)

    # Remove any existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        fmt=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    # File handler with rotation
    try:
        log_path = Path(resolved_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=resolved_max_bytes,
            backupCount=resolved_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except (OSError, PermissionError):
        # If we can't write to the log file, continue without file logging
        pass

    # Console handler (stderr) for WARNING and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    _logger = logger
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get the x-digest logger or a child logger.

    If setup_logging() hasn't been called yet, returns a basic logger
    that outputs to stderr.

    Args:
        name: Optional child logger name (e.g., "fetch", "digest")

    Returns:
        Logger instance
    """
    global _logger

    if _logger is None:
        # Return a basic logger if not configured yet
        logger = logging.getLogger("x_digest")
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT, DEFAULT_DATE_FORMAT))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        _logger = logger

    if name:
        return _logger.getChild(name)
    return _logger

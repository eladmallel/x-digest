"""Tests for logging configuration and behavior."""

import logging
import os
import json
from pathlib import Path
import pytest

from x_digest.logging import (
    setup_logging,
    get_logger,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_FORMAT,
    DEFAULT_MAX_BYTES,
    DEFAULT_BACKUP_COUNT,
)


class TestSetupLogging:
    """Tests for logger setup and configuration."""

    def test_returns_logger(self, tmp_path):
        """setup_logging returns a Logger instance."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file))
        assert isinstance(logger, logging.Logger)
        assert logger.name == "x_digest"

    def test_creates_log_file(self, tmp_path):
        """Logger creates log file on first write."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file))
        logger.info("Test message")
        # Flush handlers
        for h in logger.handlers:
            h.flush()
        assert log_file.exists()

    def test_log_format_has_timestamp(self, tmp_path):
        """Log entries contain timestamps."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="DEBUG")
        logger.info("Timestamp test")
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text()
        # Should contain ISO-style date
        assert "202" in content  # Year starts with 202x
        assert "INFO" in content
        assert "Timestamp test" in content

    def test_log_format_has_level(self, tmp_path):
        """Log entries contain the log level."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="DEBUG")
        logger.warning("Warning test")
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text()
        assert "[WARNING]" in content

    def test_log_format_has_module_name(self, tmp_path):
        """Log entries contain the logger name."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="DEBUG")
        logger.info("Module test")
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text()
        assert "x_digest" in content


class TestLogLevel:
    """Tests for log level configuration."""

    def test_default_level_is_info(self, tmp_path):
        """Default log level is INFO."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file))
        assert logger.level == logging.INFO

    def test_explicit_level_override(self, tmp_path):
        """Explicit log_level parameter overrides everything."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_env_var_override(self, tmp_path, monkeypatch):
        """LOG_LEVEL environment variable sets log level."""
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file))
        assert logger.level == logging.WARNING

    def test_config_level(self, tmp_path):
        """Config file log level is used when no env var."""
        log_file = tmp_path / "test.log"
        config = {"logging": {"level": "ERROR"}}
        logger = setup_logging(config=config, log_file=str(log_file))
        assert logger.level == logging.ERROR

    def test_explicit_beats_env(self, tmp_path, monkeypatch):
        """Explicit parameter beats environment variable."""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_level_filtering(self, tmp_path):
        """Log level filters lower-priority messages."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="WARNING")
        logger.debug("Should not appear")
        logger.info("Should not appear")
        logger.warning("Should appear")
        for h in logger.handlers:
            h.flush()
        content = log_file.read_text()
        assert "Should not appear" not in content
        assert "Should appear" in content

    def test_invalid_level_falls_back(self, tmp_path):
        """Invalid log level falls back to INFO."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=str(log_file), log_level="INVALID")
        assert logger.level == logging.INFO


class TestLogRotation:
    """Tests for log file rotation."""

    def test_rotation_at_max_size(self, tmp_path):
        """Log file rotates when it exceeds max size."""
        log_file = tmp_path / "test.log"
        # Use very small max_bytes to trigger rotation quickly
        logger = setup_logging(
            log_file=str(log_file),
            max_bytes=500,
            backup_count=3,
            log_level="DEBUG",
        )

        # Write enough to trigger rotation
        for i in range(100):
            logger.info("Rotation test message number %d with some padding to increase size", i)

        for h in logger.handlers:
            h.flush()

        # Check that backup files were created
        log_files = list(tmp_path.glob("test.log*"))
        assert len(log_files) > 1, f"Expected rotation, got: {log_files}"

    def test_backup_count_respected(self, tmp_path):
        """No more than backup_count backup files are kept."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(
            log_file=str(log_file),
            max_bytes=200,
            backup_count=2,
            log_level="DEBUG",
        )

        # Write a lot to trigger multiple rotations
        for i in range(200):
            logger.info("Backup count test %d with padding to fill the file quickly", i)

        for h in logger.handlers:
            h.flush()

        # Should have at most: test.log, test.log.1, test.log.2
        log_files = list(tmp_path.glob("test.log*"))
        assert len(log_files) <= 3  # main + 2 backups


class TestLogFileLocation:
    """Tests for log file path configuration."""

    def test_config_file_path(self, tmp_path):
        """Config file can set log file location."""
        custom_path = tmp_path / "custom" / "logs" / "app.log"
        config = {"logging": {"file": str(custom_path)}}
        logger = setup_logging(config=config)
        logger.info("Custom path test")
        for h in logger.handlers:
            h.flush()
        assert custom_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        """Logger creates parent directories if needed."""
        deep_path = tmp_path / "a" / "b" / "c" / "test.log"
        logger = setup_logging(log_file=str(deep_path))
        logger.info("Deep path test")
        for h in logger.handlers:
            h.flush()
        assert deep_path.exists()

    def test_explicit_path_overrides_config(self, tmp_path):
        """Explicit log_file parameter overrides config."""
        config_path = tmp_path / "config.log"
        explicit_path = tmp_path / "explicit.log"
        config = {"logging": {"file": str(config_path)}}
        logger = setup_logging(config=config, log_file=str(explicit_path))
        logger.info("Override test")
        for h in logger.handlers:
            h.flush()
        assert explicit_path.exists()
        assert not config_path.exists()


class TestGetLogger:
    """Tests for get_logger helper."""

    def test_get_root_logger(self, tmp_path):
        """get_logger returns root x_digest logger."""
        log_file = tmp_path / "test.log"
        setup_logging(log_file=str(log_file))
        logger = get_logger()
        assert logger.name == "x_digest"

    def test_get_child_logger(self, tmp_path):
        """get_logger with name returns child logger."""
        log_file = tmp_path / "test.log"
        setup_logging(log_file=str(log_file))
        logger = get_logger("fetch")
        assert logger.name == "x_digest.fetch"

    def test_child_logger_inherits_level(self, tmp_path):
        """Child loggers inherit parent's log level."""
        log_file = tmp_path / "test.log"
        setup_logging(log_file=str(log_file), log_level="WARNING")
        child = get_logger("pipeline")
        # Child should inherit parent's effective level
        assert child.getEffectiveLevel() == logging.WARNING

    def test_get_logger_before_setup(self):
        """get_logger works even before setup_logging is called."""
        # Reset the global logger
        import x_digest.logging as log_mod
        old_logger = log_mod._logger
        log_mod._logger = None
        try:
            logger = get_logger()
            assert isinstance(logger, logging.Logger)
        finally:
            log_mod._logger = old_logger

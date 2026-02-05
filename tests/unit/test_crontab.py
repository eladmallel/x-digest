"""Tests for crontab generation from config schedules."""

import json
import os
import pytest
from unittest.mock import patch, Mock

from x_digest.cli import (
    generate_crontab,
    check_crontab_staleness,
    cmd_crontab,
    parse_args,
)
from x_digest.errors import ConfigError, ErrorCode


class TestGenerateCrontab:
    """Tests for crontab output generation."""

    def test_single_schedule(self):
        """Single schedule generates valid crontab line."""
        config = {
            "schedules": [
                {"name": "morning", "list": "ai-dev", "cron": "0 12 * * *"}
            ]
        }
        output = generate_crontab(config)
        assert "0 12 * * *" in output
        assert "run --list ai-dev" in output

    def test_multiple_schedules(self):
        """Multiple schedules generate multiple crontab lines."""
        config = {
            "schedules": [
                {"name": "morning-ai", "list": "ai-dev", "cron": "0 12 * * *", "description": "7am EST"},
                {"name": "evening-ai", "list": "ai-dev", "cron": "0 0 * * *", "description": "7pm EST"},
                {"name": "morning-invest", "list": "investing", "cron": "0 13 * * 1-5", "description": "8am EST weekdays"},
            ]
        }
        output = generate_crontab(config)
        assert "0 12 * * *" in output
        assert "0 0 * * *" in output
        assert "0 13 * * 1-5" in output
        assert "run --list ai-dev" in output
        assert "run --list investing" in output

    def test_includes_description_comment(self):
        """Schedule description appears as comment."""
        config = {
            "schedules": [
                {"name": "morning", "list": "ai-dev", "cron": "0 12 * * *", "description": "7am EST"}
            ]
        }
        output = generate_crontab(config)
        assert "# morning: 7am EST" in output

    def test_includes_name_comment_without_description(self):
        """Schedule name appears as comment when no description."""
        config = {
            "schedules": [
                {"name": "nightly", "list": "test", "cron": "0 3 * * *"}
            ]
        }
        output = generate_crontab(config)
        assert "# nightly" in output

    def test_no_schedules(self):
        """Empty schedules array produces informative comment."""
        config = {"schedules": []}
        output = generate_crontab(config)
        assert "No schedules" in output

    def test_missing_schedules_key(self):
        """Missing schedules key produces informative comment."""
        config = {}
        output = generate_crontab(config)
        assert "No schedules" in output

    def test_config_path_in_command(self):
        """Config path is included in generated commands."""
        config = {
            "schedules": [
                {"name": "test", "list": "ai-dev", "cron": "0 12 * * *"}
            ]
        }
        output = generate_crontab(config, config_path="/etc/x-digest/config.json")
        assert "--config /etc/x-digest/config.json" in output

    def test_skips_invalid_schedules(self):
        """Schedules without cron or list are skipped."""
        config = {
            "schedules": [
                {"name": "no-cron", "list": "test"},
                {"name": "no-list", "cron": "0 12 * * *"},
                {"name": "valid", "list": "ai-dev", "cron": "0 0 * * *"},
            ]
        }
        output = generate_crontab(config)
        lines = [l for l in output.split("\n") if l.strip() and not l.startswith("#")]
        assert len(lines) == 1
        assert "run --list ai-dev" in lines[0]

    def test_header_comment(self):
        """Output includes header comment."""
        config = {
            "schedules": [
                {"name": "test", "list": "ai-dev", "cron": "0 12 * * *"}
            ]
        }
        output = generate_crontab(config)
        assert "x-digest crontab" in output.lower() or "generated from config" in output.lower()

    def test_uses_python_module_command(self):
        """Generated command uses python3 -m x_digest."""
        config = {
            "schedules": [
                {"name": "test", "list": "ai-dev", "cron": "0 12 * * *"}
            ]
        }
        output = generate_crontab(config)
        assert "python3 -m x_digest" in output


class TestCrontabStaleness:
    """Tests for stale crontab detection."""

    def test_no_crontab_file(self, tmp_path):
        """No crontab file returns None (no warning)."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{}')
        result = check_crontab_staleness(str(config_file))
        # No /etc/cron.d/x-digest, so no staleness detected
        assert result is None

    def test_nonexistent_config(self):
        """Nonexistent config returns None."""
        result = check_crontab_staleness("/nonexistent/config.json")
        assert result is None


class TestCmdCrontab:
    """Tests for the crontab CLI subcommand."""

    def test_valid_config_outputs_crontab(self, tmp_path, capsys):
        """crontab subcommand outputs crontab entries."""
        config_file = tmp_path / "config.json"
        config_data = {
            "version": 1,
            "lists": {"ai-dev": {"id": "123"}},
            "schedules": [
                {"name": "morning", "list": "ai-dev", "cron": "0 12 * * *"}
            ]
        }
        config_file.write_text(json.dumps(config_data))

        args = parse_args(["crontab", "--config", str(config_file)])
        result = cmd_crontab(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "0 12 * * *" in captured.out
        assert "run --list ai-dev" in captured.out

    def test_invalid_config(self, tmp_path, capsys):
        """crontab subcommand handles invalid config."""
        config_file = tmp_path / "config.json"
        config_file.write_text("invalid json")

        args = parse_args(["crontab", "--config", str(config_file)])
        result = cmd_crontab(args)

        assert result == 1

    def test_parse_crontab_subcommand(self):
        """crontab subcommand parses correctly."""
        args = parse_args(["crontab"])
        assert args.command == "crontab"


class TestScheduleParsing:
    """Tests for parsing various schedule formats."""

    def test_every_minute(self):
        """Every-minute schedule."""
        config = {
            "schedules": [
                {"name": "frequent", "list": "test", "cron": "* * * * *"}
            ]
        }
        output = generate_crontab(config)
        assert "* * * * *" in output

    def test_complex_cron_expression(self):
        """Complex cron expression with ranges and steps."""
        config = {
            "schedules": [
                {"name": "complex", "list": "test", "cron": "*/15 9-17 * * 1-5"}
            ]
        }
        output = generate_crontab(config)
        assert "*/15 9-17 * * 1-5" in output

    def test_schedule_with_all_fields(self):
        """Schedule with all optional fields."""
        config = {
            "schedules": [
                {
                    "name": "full-schedule",
                    "list": "ai-dev",
                    "cron": "0 12 * * *",
                    "description": "Morning digest at 7am EST",
                }
            ]
        }
        output = generate_crontab(config)
        assert "0 12 * * *" in output
        assert "Morning digest" in output
        assert "run --list ai-dev" in output

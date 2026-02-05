"""Tests for CLI argument parsing, config discovery, and pipeline orchestration."""

import json
import os
import sys
import pytest
from datetime import datetime, UTC, timedelta
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock, call

from x_digest.cli import (
    parse_args,
    find_config_file,
    cmd_validate,
    cmd_run,
    run_pipeline,
    _load_env,
    _deliver_digest,
    main,
)
from x_digest.errors import ConfigError, BirdError, LLMError, DeliveryError, ErrorCode


# === Argument Parsing Tests ===

class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_run_command_basic(self):
        """Run command with required --list argument."""
        args = parse_args(["run", "--list", "ai-dev"])

        assert args.command == "run"
        assert args.list_name == "ai-dev"
        assert args.dry_run is False
        assert args.force is False
        assert args.preview is False
        assert args.hours is None

    def test_run_command_all_flags(self):
        """Run command with all optional flags."""
        args = parse_args([
            "run", "--list", "investing",
            "--dry-run", "--force", "--preview",
            "--hours", "12"
        ])

        assert args.command == "run"
        assert args.list_name == "investing"
        assert args.dry_run is True
        assert args.force is True
        assert args.preview is True
        assert args.hours == 12.0

    def test_run_command_hours_float(self):
        """Hours accepts float values."""
        args = parse_args(["run", "--list", "test", "--hours", "6.5"])
        assert args.hours == 6.5

    def test_validate_command(self):
        """Validate command parses correctly."""
        args = parse_args(["validate"])
        assert args.command == "validate"

    def test_validate_with_config(self):
        """Validate with custom config path."""
        args = parse_args(["validate", "--config", "/custom/path.json"])
        assert args.command == "validate"
        assert args.config == "/custom/path.json"

    def test_global_config_option(self):
        """Global --config option works with subcommands."""
        args = parse_args(["--config", "/path/to/config.json", "run", "--list", "test"])
        assert args.config == "/path/to/config.json"
        assert args.command == "run"
        assert args.list_name == "test"

    def test_version_flag(self):
        """--version flag works."""
        with pytest.raises(SystemExit) as exc:
            parse_args(["--version"])
        assert exc.value.code == 0

    def test_no_command_exits(self):
        """No command shows help and exits."""
        with pytest.raises(SystemExit) as exc:
            parse_args([])
        assert exc.value.code == 0

    def test_run_missing_list_exits(self):
        """Run without --list exits with error."""
        with pytest.raises(SystemExit) as exc:
            parse_args(["run"])
        assert exc.value.code != 0

    def test_watch_command(self):
        """Watch command parses correctly."""
        args = parse_args(["watch", "--list", "ai-dev", "--every", "12h"])
        assert args.command == "watch"
        assert args.list_name == "ai-dev"
        assert args.every == "12h"


# === Config Discovery Tests ===

class TestFindConfigFile:
    """Tests for config file discovery."""

    def test_explicit_path_found(self, tmp_path):
        """Explicit config path that exists is returned."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"version": 1}')

        result = find_config_file(str(config_file))
        assert result == str(config_file)

    def test_explicit_path_not_found(self):
        """Explicit config path that doesn't exist raises error."""
        with pytest.raises(ConfigError) as exc:
            find_config_file("/nonexistent/config.json")
        assert exc.value.code == ErrorCode.CONFIG_FILE_NOT_FOUND

    def test_search_order_cwd(self, tmp_path, monkeypatch):
        """Config in CWD is found first."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "x-digest-config.json"
        config_file.write_text('{"version": 1}')

        result = find_config_file()
        assert result == "./x-digest-config.json"

    def test_search_order_config_dir(self, tmp_path, monkeypatch):
        """Config in config/ subdirectory is found."""
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "x-digest-config.json"
        config_file.write_text('{"version": 1}')

        result = find_config_file()
        assert "config/x-digest-config.json" in result

    def test_no_config_found_raises(self, tmp_path, monkeypatch):
        """No config found raises ConfigError."""
        monkeypatch.chdir(tmp_path)
        # Override home to avoid finding real config
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))

        with pytest.raises(ConfigError) as exc:
            find_config_file()
        assert exc.value.code == ErrorCode.CONFIG_FILE_NOT_FOUND


# === cmd_validate Tests ===

class TestCmdValidate:
    """Tests for validate subcommand."""

    def test_valid_config(self, tmp_path, capsys):
        """Valid config reports success."""
        config_file = tmp_path / "config.json"
        config_data = {
            "version": 1,
            "lists": {
                "ai-dev": {
                    "id": "12345",
                    "display_name": "AI & Dev",
                    "emoji": "🤖",
                    "enabled": True
                }
            }
        }
        config_file.write_text(json.dumps(config_data))

        args = parse_args(["validate", "--config", str(config_file)])
        result = cmd_validate(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "✅" in captured.out
        assert "AI & Dev" in captured.out

    def test_invalid_config(self, tmp_path, capsys):
        """Invalid config reports error."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not json")

        args = parse_args(["validate", "--config", str(config_file)])
        result = cmd_validate(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "❌" in captured.err

    def test_missing_config(self, capsys):
        """Missing config reports error."""
        args = parse_args(["validate", "--config", "/nonexistent.json"])
        result = cmd_validate(args)

        assert result == 1

    def test_config_with_schedules(self, tmp_path, capsys):
        """Config with schedules shows schedule info."""
        config_file = tmp_path / "config.json"
        config_data = {
            "version": 1,
            "lists": {"test": {"id": "123"}},
            "schedules": [
                {"name": "morning", "list": "test", "cron": "0 12 * * *", "description": "7am"}
            ]
        }
        config_file.write_text(json.dumps(config_data))

        args = parse_args(["validate", "--config", str(config_file)])
        result = cmd_validate(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "morning" in captured.out

    def test_config_with_delivery(self, tmp_path, capsys):
        """Config with delivery provider shows delivery info."""
        config_file = tmp_path / "config.json"
        config_data = {
            "version": 1,
            "lists": {"test": {"id": "123"}},
            "delivery": {"provider": "whatsapp"}
        }
        config_file.write_text(json.dumps(config_data))

        args = parse_args(["validate", "--config", str(config_file)])
        result = cmd_validate(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "whatsapp" in captured.out


# === cmd_run Tests ===

class TestCmdRun:
    """Tests for run subcommand."""

    @patch('x_digest.cli.run_pipeline')
    @patch('x_digest.cli.load_config')
    @patch('x_digest.cli.find_config_file')
    @patch('x_digest.cli._load_env')
    def test_successful_run(self, mock_env, mock_find, mock_load, mock_pipeline):
        """Successful run returns 0."""
        mock_find.return_value = "/path/to/config.json"
        mock_load.return_value = {"version": 1, "lists": {"test": {"id": "123"}}}
        mock_pipeline.return_value = True

        args = parse_args(["run", "--list", "test"])
        result = cmd_run(args)

        assert result == 0
        mock_pipeline.assert_called_once()

    @patch('x_digest.cli.run_pipeline')
    @patch('x_digest.cli.load_config')
    @patch('x_digest.cli.find_config_file')
    @patch('x_digest.cli._load_env')
    def test_pipeline_failure_returns_1(self, mock_env, mock_find, mock_load, mock_pipeline):
        """Pipeline failure returns 1."""
        mock_find.return_value = "/path/to/config.json"
        mock_load.return_value = {"version": 1}
        mock_pipeline.return_value = False

        args = parse_args(["run", "--list", "test"])
        result = cmd_run(args)

        assert result == 1

    @patch('x_digest.cli.load_config')
    @patch('x_digest.cli.find_config_file')
    @patch('x_digest.cli._load_env')
    def test_config_error_returns_1(self, mock_env, mock_find, mock_load):
        """Config error returns 1."""
        mock_find.side_effect = ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)

        args = parse_args(["run", "--list", "test"])
        result = cmd_run(args)

        assert result == 1

    @patch('x_digest.cli.run_pipeline')
    @patch('x_digest.cli.load_config')
    @patch('x_digest.cli.find_config_file')
    @patch('x_digest.cli._load_env')
    def test_bird_error_returns_1(self, mock_env, mock_find, mock_load, mock_pipeline):
        """BirdError returns 1."""
        mock_find.return_value = "/path/config.json"
        mock_load.return_value = {"version": 1}
        mock_pipeline.side_effect = BirdError(ErrorCode.BIRD_AUTH_FAILED)

        args = parse_args(["run", "--list", "test"])
        result = cmd_run(args)

        assert result == 1

    @patch('x_digest.cli.run_pipeline')
    @patch('x_digest.cli.load_config')
    @patch('x_digest.cli.find_config_file')
    @patch('x_digest.cli._load_env')
    def test_llm_error_returns_1(self, mock_env, mock_find, mock_load, mock_pipeline):
        """LLMError returns 1."""
        mock_find.return_value = "/path/config.json"
        mock_load.return_value = {"version": 1}
        mock_pipeline.side_effect = LLMError(ErrorCode.LLM_TIMEOUT)

        args = parse_args(["run", "--list", "test"])
        result = cmd_run(args)

        assert result == 1

    @patch('x_digest.cli.run_pipeline')
    @patch('x_digest.cli.load_config')
    @patch('x_digest.cli.find_config_file')
    @patch('x_digest.cli._load_env')
    def test_flags_passed_to_pipeline(self, mock_env, mock_find, mock_load, mock_pipeline):
        """CLI flags are passed to run_pipeline."""
        mock_find.return_value = "/path/config.json"
        mock_load.return_value = {"version": 1}
        mock_pipeline.return_value = True

        args = parse_args(["run", "--list", "test", "--dry-run", "--force", "--preview", "--hours", "6"])
        cmd_run(args)

        mock_pipeline.assert_called_once_with(
            list_name="test",
            config={"version": 1},
            dry_run=True,
            force=True,
            preview=True,
            hours=6.0,
            no_artifacts=False
        )


# === run_pipeline Tests ===

class TestRunPipeline:
    """Tests for the full digest pipeline orchestration."""

    def _make_config(self, list_name="test", list_id="12345"):
        """Create a minimal valid config."""
        return {
            "version": 1,
            "lists": {
                list_name: {
                    "id": list_id,
                    "display_name": "Test List",
                    "emoji": "📋"
                }
            },
            "defaults": {
                "llm": {"provider": "gemini", "model": "gemini-2.0-flash"},
                "timezone": "UTC",
                "pre_summarization": {
                    "enabled": True,
                    "long_tweet_chars": 500,
                    "long_quote_chars": 300,
                    "long_combined_chars": 600,
                    "thread_min_tweets": 2,
                    "max_summary_tokens": 300
                },
                "token_limits": {
                    "max_input_tokens": 100000,
                    "max_output_tokens": 4000,
                    "warn_at_percent": 80
                }
            },
            "delivery": {
                "provider": "whatsapp",
                "whatsapp": {
                    "gateway_url": "http://localhost:3420",
                    "recipient": "+1234567890"
                }
            },
            "retry": {"max_attempts": 3},
            "idempotency_window_minutes": 30
        }

    @patch('x_digest.status.update_status')
    @patch('x_digest.status.load_status')
    @patch('x_digest.fetch.fetch_tweets_from_bird')
    def test_preview_mode_no_llm(self, mock_fetch, mock_load_status, mock_update, capsys):
        """Preview mode fetches and shows stats without LLM call."""
        mock_load_status.return_value = {"lists": {}}

        # Create a proper Tweet mock
        tweet_mock = Mock()
        tweet_mock.id = "1"
        tweet_mock.text = "Test tweet"
        tweet_mock.author = Mock(username="user1", name="User One")
        tweet_mock.created_at = "Wed Feb 04 19:00:43 +0000 2026"
        tweet_mock.conversation_id = "1"
        tweet_mock.quoted_tweet = None
        tweet_mock.in_reply_to_status_id = None
        tweet_mock.media = None
        tweet_mock.like_count = 5
        tweet_mock.retweet_count = 2
        tweet_mock.reply_count = 1
        tweet_mock.author_id = "1"

        mock_fetch.return_value = [tweet_mock]

        config = self._make_config()
        result = run_pipeline("test", config, preview=True, force=True, hours=24)

        assert result is True
        captured = capsys.readouterr()
        assert "Preview complete" in captured.out

    @patch('x_digest.status.update_status')
    @patch('x_digest.status.load_status')
    @patch('x_digest.fetch.fetch_tweets_from_bird')
    def test_empty_tweets_dry_run(self, mock_fetch, mock_load_status, mock_update, capsys):
        """No tweets with dry-run shows empty digest."""
        mock_load_status.return_value = {"lists": {}}
        mock_fetch.return_value = []

        config = self._make_config()
        result = run_pipeline("test", config, dry_run=True, force=True, hours=24)

        assert result is True
        captured = capsys.readouterr()
        assert "No tweets found" in captured.out or "dry-run" in captured.out

    @patch('x_digest.status.should_run')
    @patch('x_digest.status.load_status')
    def test_idempotency_skip(self, mock_load_status, mock_should_run, capsys):
        """Pipeline skips if within idempotency window."""
        mock_load_status.return_value = {
            "lists": {"test": {"last_run": datetime.now(UTC).isoformat()}}
        }
        mock_should_run.return_value = False

        config = self._make_config()
        result = run_pipeline("test", config)

        assert result is True
        captured = capsys.readouterr()
        assert "Skipping" in captured.out

    @patch('x_digest.status.update_status')
    @patch('x_digest.status.load_status')
    @patch('x_digest.fetch.fetch_tweets_from_bird')
    def test_force_bypasses_idempotency(self, mock_fetch, mock_load_status, mock_update, capsys):
        """Force flag bypasses idempotency check."""
        mock_load_status.return_value = {
            "lists": {"test": {"last_run": datetime.now(UTC).isoformat()}}
        }
        mock_fetch.return_value = []

        config = self._make_config()
        result = run_pipeline("test", config, force=True, dry_run=True, hours=24)

        # Should NOT skip even if recent run
        assert result is True
        captured = capsys.readouterr()
        assert "Skipping" not in captured.out

    @patch('x_digest.status.update_status')
    @patch('x_digest.status.load_status')
    @patch('x_digest.fetch.fetch_tweets_from_bird')
    def test_hours_override(self, mock_fetch, mock_load_status, mock_update, capsys):
        """--hours flag overrides status-based time window."""
        mock_load_status.return_value = {"lists": {}}
        mock_fetch.return_value = []

        config = self._make_config()
        result = run_pipeline("test", config, force=True, hours=6, dry_run=True)

        assert result is True
        captured = capsys.readouterr()
        assert "Time window" in captured.out

    def test_invalid_list_raises(self):
        """Invalid list name raises ConfigError."""
        config = self._make_config()

        with pytest.raises(ConfigError):
            run_pipeline("nonexistent", config, force=True)


# === _deliver_digest Tests ===

class TestDeliverDigest:
    """Tests for digest delivery helper."""

    @patch('x_digest.delivery.base.send_digest')
    @patch('x_digest.delivery.base.get_provider')
    @patch('x_digest.digest.split_digest')
    def test_successful_delivery(self, mock_split, mock_get_provider, mock_send):
        """Successful delivery returns True."""
        mock_split.return_value = ["Part 1"]
        mock_get_provider.return_value = Mock()
        mock_send.return_value = True

        config = {
            "delivery": {
                "provider": "whatsapp",
                "whatsapp": {"gateway_url": "http://localhost", "recipient": "+1"}
            },
            "retry": {"max_attempts": 3}
        }

        result = _deliver_digest("Test digest", config, {})

        assert result is True

    @patch('x_digest.delivery.base.send_digest')
    @patch('x_digest.delivery.base.get_provider')
    @patch('x_digest.digest.split_digest')
    def test_failed_delivery(self, mock_split, mock_get_provider, mock_send):
        """Failed delivery returns False."""
        mock_split.return_value = ["Part 1"]
        mock_get_provider.return_value = Mock()
        mock_send.return_value = False

        config = {
            "delivery": {
                "provider": "whatsapp",
                "whatsapp": {"gateway_url": "http://localhost", "recipient": "+1"}
            },
            "retry": {"max_attempts": 3}
        }

        result = _deliver_digest("Test digest", config, {})

        assert result is False

    def test_env_overrides_config(self, monkeypatch):
        """Environment variables override config delivery values."""
        monkeypatch.setenv("WHATSAPP_GATEWAY", "http://override:3420")
        monkeypatch.setenv("WHATSAPP_RECIPIENT", "+9999999")

        config = {
            "delivery": {},
            "retry": {"max_attempts": 1}
        }

        with patch('x_digest.delivery.base.get_provider') as mock_provider, \
             patch('x_digest.delivery.base.send_digest') as mock_send, \
             patch('x_digest.digest.split_digest') as mock_split:
            mock_split.return_value = ["Part 1"]
            mock_provider.return_value = Mock()
            mock_send.return_value = True

            _deliver_digest("Test", config, {})

            # Verify get_provider was called with overridden values
            call_args = mock_provider.call_args[0][0]
            assert call_args["whatsapp"]["gateway_url"] == "http://override:3420"
            assert call_args["whatsapp"]["recipient"] == "+9999999"


# === _load_env Tests ===

class TestLoadEnv:
    """Tests for environment loading."""

    def test_load_env_existing_file(self, tmp_path, monkeypatch):
        """Loads .env file when it exists."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR_CLI=hello\n")
        monkeypatch.chdir(tmp_path)

        _load_env()

        # python-dotenv should have loaded the file (if installed)

    def test_load_env_no_file(self, tmp_path, monkeypatch):
        """No .env file doesn't crash."""
        monkeypatch.chdir(tmp_path)
        _load_env()  # Should not raise


# === main() Tests ===

class TestMain:
    """Tests for main CLI entry point."""

    @patch('x_digest.cli.cmd_validate')
    @patch('x_digest.cli.parse_args')
    def test_main_validate(self, mock_parse, mock_validate):
        """main() dispatches to validate handler."""
        mock_parse.return_value = Mock(command="validate", config=None)
        mock_validate.return_value = 0

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    @patch('x_digest.cli.cmd_run')
    @patch('x_digest.cli.parse_args')
    def test_main_run(self, mock_parse, mock_run):
        """main() dispatches to run handler."""
        mock_parse.return_value = Mock(command="run")
        mock_run.return_value = 0

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0

    @patch('x_digest.cli.parse_args')
    def test_main_unknown_command(self, mock_parse):
        """Unknown command exits with error."""
        mock_parse.return_value = Mock(command="unknown")

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    @patch('x_digest.cli.parse_args')
    def test_main_keyboard_interrupt(self, mock_parse):
        """Keyboard interrupt exits cleanly."""
        mock_parse.side_effect = KeyboardInterrupt()

        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 130

"""Tests for tweet fetching via bird CLI."""

import json
import os
import subprocess
import pytest
from datetime import datetime, UTC, timedelta
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

from x_digest.fetch import (
    fetch_tweets_from_bird,
    check_bird_auth,
    _load_bird_env,
    _find_bird_executable,
    _find_runtime,
    _build_base_command,
    _build_bird_command,
    _build_subprocess_env,
    _run_bird_command,
    _filter_tweets_by_time,
    _map_bird_error,
    DEFAULT_BIRD_ENV_PATH,
    DEFAULT_FETCH_COUNT,
    BIRD_TIMEOUT_SECONDS,
)
from x_digest.models import Tweet, Author, parse_tweets
from x_digest.errors import BirdError, ErrorCode


def make_tweet(**kwargs):
    """Helper to create a test tweet with defaults."""
    defaults = {
        "id": "123",
        "text": "Test tweet",
        "created_at": "Wed Feb 04 19:00:43 +0000 2026",
        "conversation_id": "123",
        "author": Author(username="testuser", name="Test User"),
        "author_id": "1",
        "reply_count": 0,
        "retweet_count": 0,
        "like_count": 0
    }
    defaults.update(kwargs)
    return Tweet(**defaults)


def make_tweet_json(**kwargs):
    """Helper to create tweet JSON data matching bird CLI output format."""
    defaults = {
        "id": "123",
        "text": "Test tweet",
        "createdAt": "Wed Feb 04 19:00:43 +0000 2026",
        "conversationId": "123",
        "author": {"username": "testuser", "name": "Test User"},
        "authorId": "1",
        "replyCount": 0,
        "retweetCount": 0,
        "likeCount": 0
    }
    defaults.update(kwargs)
    return defaults


def load_fixture(filename):
    """Load test fixture data."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "tweets" / filename
    with open(fixture_path) as f:
        return json.load(f)


# === _load_bird_env tests ===

class TestLoadBirdEnv:
    """Tests for loading bird environment file."""

    def test_load_valid_env(self, tmp_path):
        """Valid env file with export statements loads correctly."""
        env_file = tmp_path / "env"
        env_file.write_text(
            'export AUTH_TOKEN="abc123"\n'
            'export CT0="def456"\n'
        )

        result = _load_bird_env(str(env_file))

        assert result["AUTH_TOKEN"] == "abc123"
        assert result["CT0"] == "def456"

    def test_load_env_without_export(self, tmp_path):
        """Env file without export keyword loads correctly."""
        env_file = tmp_path / "env"
        env_file.write_text(
            'AUTH_TOKEN=abc123\n'
            'CT0=def456\n'
        )

        result = _load_bird_env(str(env_file))

        assert result["AUTH_TOKEN"] == "abc123"
        assert result["CT0"] == "def456"

    def test_load_env_with_single_quotes(self, tmp_path):
        """Env file with single-quoted values loads correctly."""
        env_file = tmp_path / "env"
        env_file.write_text(
            "export AUTH_TOKEN='abc123'\n"
            "export CT0='def456'\n"
        )

        result = _load_bird_env(str(env_file))

        assert result["AUTH_TOKEN"] == "abc123"
        assert result["CT0"] == "def456"

    def test_load_env_with_comments(self, tmp_path):
        """Comments and blank lines are ignored."""
        env_file = tmp_path / "env"
        env_file.write_text(
            '# Twitter cookies\n'
            '\n'
            'export AUTH_TOKEN="abc123"\n'
            '# ct0 token\n'
            'export CT0="def456"\n'
        )

        result = _load_bird_env(str(env_file))

        assert result["AUTH_TOKEN"] == "abc123"
        assert result["CT0"] == "def456"

    def test_load_env_twitter_prefixed(self, tmp_path):
        """Env file with TWITTER_ prefix works."""
        env_file = tmp_path / "env"
        env_file.write_text(
            'export TWITTER_AUTH_TOKEN="abc123"\n'
            'export TWITTER_CT0="def456"\n'
        )

        result = _load_bird_env(str(env_file))

        assert result["AUTH_TOKEN"] == "abc123"
        assert result["CT0"] == "def456"

    def test_missing_env_file_raises(self):
        """Missing env file raises BirdError."""
        with pytest.raises(BirdError) as exc:
            _load_bird_env("/nonexistent/path/env")

        assert exc.value.code == ErrorCode.BIRD_AUTH_FAILED
        assert "not found" in str(exc.value)

    def test_missing_auth_token_raises(self, tmp_path):
        """Missing AUTH_TOKEN raises BirdError."""
        env_file = tmp_path / "env"
        env_file.write_text('export CT0="def456"\n')

        with pytest.raises(BirdError) as exc:
            _load_bird_env(str(env_file))

        assert exc.value.code == ErrorCode.BIRD_AUTH_FAILED
        assert "Missing AUTH_TOKEN" in str(exc.value)

    def test_missing_ct0_raises(self, tmp_path):
        """Missing CT0 raises BirdError."""
        env_file = tmp_path / "env"
        env_file.write_text('export AUTH_TOKEN="abc123"\n')

        with pytest.raises(BirdError) as exc:
            _load_bird_env(str(env_file))

        assert exc.value.code == ErrorCode.BIRD_AUTH_FAILED
        assert "Missing" in str(exc.value)

    def test_empty_env_file_raises(self, tmp_path):
        """Empty env file raises BirdError."""
        env_file = tmp_path / "env"
        env_file.write_text('')

        with pytest.raises(BirdError) as exc:
            _load_bird_env(str(env_file))

        assert exc.value.code == ErrorCode.BIRD_AUTH_FAILED

    def test_tilde_expansion(self, tmp_path):
        """Tilde in path is expanded."""
        # This test just verifies the expanduser call doesn't break
        with pytest.raises(BirdError):
            _load_bird_env("~/nonexistent/bird/env")


# === _find_bird_executable tests ===

class TestFindBirdExecutable:
    """Tests for finding the bird CLI executable."""

    @patch.dict('os.environ', {}, clear=False)
    @patch('x_digest.fetch.shutil.which')
    def test_bird_in_path(self, mock_which):
        """Bird found in PATH."""
        # Ensure BIRD_PATH is not set
        os.environ.pop('BIRD_PATH', None)
        mock_which.return_value = "/usr/local/bin/bird"
        result = _find_bird_executable()
        assert result == "/usr/local/bin/bird"

    @patch.dict('os.environ', {'BIRD_PATH': '/custom/bird'})
    @patch('os.path.exists', return_value=True)
    def test_bird_from_env_var(self, mock_exists):
        """Bird found via BIRD_PATH env var."""
        result = _find_bird_executable()
        assert result == "/custom/bird"

    @patch.dict('os.environ', {}, clear=False)
    @patch('x_digest.fetch.shutil.which', return_value=None)
    def test_bird_not_found(self, mock_which):
        """Bird not found anywhere."""
        os.environ.pop('BIRD_PATH', None)
        result = _find_bird_executable()
        assert result is None


# === _find_runtime tests ===

class TestFindRuntime:
    """Tests for finding JavaScript runtime."""

    @patch('x_digest.fetch.shutil.which')
    def test_bun_found(self, mock_which):
        """Bun found in PATH."""
        mock_which.side_effect = lambda x: "/usr/local/bin/bun" if x == "bun" else None
        result = _find_runtime()
        assert result == "/usr/local/bin/bun"

    @patch('x_digest.fetch.shutil.which')
    def test_node_found(self, mock_which):
        """Node found in PATH (bun not available)."""
        mock_which.side_effect = lambda x: "/usr/bin/node" if x == "node" else None
        result = _find_runtime()
        assert result == "/usr/bin/node"

    @patch('x_digest.fetch.shutil.which', return_value=None)
    def test_no_runtime_found(self, mock_which):
        """No JavaScript runtime found."""
        result = _find_runtime()
        assert result is None


# === _filter_tweets_by_time tests ===

class TestFilterTweetsByTime:
    """Tests for time-based tweet filtering."""

    def test_filter_keeps_recent(self):
        """Tweets after since timestamp are kept."""
        since = datetime(2026, 2, 4, 18, 0, tzinfo=UTC)  # 6pm
        tweets = [
            make_tweet(id="1", created_at="Wed Feb 04 19:00:43 +0000 2026"),  # 7pm - keep
            make_tweet(id="2", created_at="Wed Feb 04 17:00:00 +0000 2026"),  # 5pm - filter
        ]

        result = _filter_tweets_by_time(tweets, since)

        assert len(result) == 1
        assert result[0].id == "1"

    def test_filter_removes_old(self):
        """Tweets before since timestamp are removed."""
        since = datetime(2026, 2, 4, 20, 0, tzinfo=UTC)
        tweets = [
            make_tweet(id="1", created_at="Wed Feb 04 19:00:43 +0000 2026"),
            make_tweet(id="2", created_at="Wed Feb 04 18:00:00 +0000 2026"),
        ]

        result = _filter_tweets_by_time(tweets, since)

        assert len(result) == 0

    def test_filter_includes_exact_time(self):
        """Tweets exactly at since timestamp are included."""
        since = datetime(2026, 2, 4, 19, 0, 43, tzinfo=UTC)
        tweets = [
            make_tweet(id="1", created_at="Wed Feb 04 19:00:43 +0000 2026"),
        ]

        result = _filter_tweets_by_time(tweets, since)

        assert len(result) == 1

    def test_filter_empty_list(self):
        """Empty tweet list returns empty."""
        since = datetime(2026, 2, 4, 18, 0, tzinfo=UTC)
        result = _filter_tweets_by_time([], since)
        assert result == []

    def test_filter_naive_datetime(self):
        """Naive datetime (no timezone) is handled correctly."""
        since = datetime(2026, 2, 4, 18, 0)  # No tzinfo
        tweets = [
            make_tweet(id="1", created_at="Wed Feb 04 19:00:43 +0000 2026"),
        ]

        result = _filter_tweets_by_time(tweets, since)

        assert len(result) == 1


# === _map_bird_error tests ===

class TestMapBirdError:
    """Tests for mapping bird CLI errors to BirdError."""

    def test_auth_error(self):
        """Auth-related stderr maps to BIRD_AUTH_FAILED."""
        err = _map_bird_error("Error: Unauthorized - invalid auth_token", 1)
        assert err.code == ErrorCode.BIRD_AUTH_FAILED

    def test_auth_error_403(self):
        """403 forbidden maps to BIRD_AUTH_FAILED."""
        err = _map_bird_error("HTTP 403 Forbidden", 1)
        assert err.code == ErrorCode.BIRD_AUTH_FAILED

    def test_rate_limit_error(self):
        """Rate limit stderr maps to BIRD_RATE_LIMITED."""
        err = _map_bird_error("Error: Rate limit exceeded. Try again later.", 1)
        assert err.code == ErrorCode.BIRD_RATE_LIMITED

    def test_rate_limit_429(self):
        """HTTP 429 maps to BIRD_RATE_LIMITED."""
        err = _map_bird_error("HTTP 429 Too Many Requests", 1)
        assert err.code == ErrorCode.BIRD_RATE_LIMITED

    def test_network_error(self):
        """Network error maps to BIRD_NETWORK_ERROR."""
        err = _map_bird_error("Error: ECONNREFUSED connect failed", 1)
        assert err.code == ErrorCode.BIRD_NETWORK_ERROR

    def test_timeout_error(self):
        """Timeout error maps to BIRD_NETWORK_ERROR."""
        err = _map_bird_error("Error: timeout waiting for response", 1)
        assert err.code == ErrorCode.BIRD_NETWORK_ERROR

    def test_not_found_error(self):
        """Not found maps to BIRD_INVALID_LIST_ID."""
        err = _map_bird_error("Error: List not found", 1)
        assert err.code == ErrorCode.BIRD_INVALID_LIST_ID

    def test_json_error(self):
        """JSON parse error maps to BIRD_JSON_PARSE_ERROR."""
        err = _map_bird_error("SyntaxError: Unexpected token in JSON", 1)
        assert err.code == ErrorCode.BIRD_JSON_PARSE_ERROR

    def test_generic_error(self):
        """Unknown error maps to BIRD_COMMAND_FAILED."""
        err = _map_bird_error("Some unknown error", 42)
        assert err.code == ErrorCode.BIRD_COMMAND_FAILED
        assert "42" in str(err)

    def test_empty_stderr(self):
        """Empty stderr maps to BIRD_COMMAND_FAILED."""
        err = _map_bird_error("", 1)
        assert err.code == ErrorCode.BIRD_COMMAND_FAILED

    def test_none_stderr(self):
        """None stderr maps to BIRD_COMMAND_FAILED."""
        err = _map_bird_error(None, 1)
        assert err.code == ErrorCode.BIRD_COMMAND_FAILED


# === _run_bird_command tests ===

class TestRunBirdCommand:
    """Tests for executing bird CLI commands."""

    @patch('x_digest.fetch.subprocess.run')
    def test_successful_command(self, mock_run):
        """Successful bird command returns stdout."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='[{"id": "123"}]',
            stderr=""
        )

        result = _run_bird_command(["bird", "list-timeline", "123"], {})

        assert result == '[{"id": "123"}]'

    @patch('x_digest.fetch.subprocess.run')
    def test_command_failure_raises(self, mock_run):
        """Failed bird command raises BirdError."""
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Error: Unauthorized"
        )

        with pytest.raises(BirdError) as exc:
            _run_bird_command(["bird", "list-timeline"], {})

        assert exc.value.code == ErrorCode.BIRD_AUTH_FAILED

    @patch('x_digest.fetch.subprocess.run')
    def test_timeout_raises(self, mock_run):
        """Command timeout raises BirdError."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bird", timeout=30)

        with pytest.raises(BirdError) as exc:
            _run_bird_command(["bird", "list-timeline"], {})

        assert exc.value.code == ErrorCode.BIRD_NETWORK_ERROR
        assert "timed out" in str(exc.value)

    @patch('x_digest.fetch.subprocess.run')
    def test_file_not_found_raises(self, mock_run):
        """Missing executable raises BirdError."""
        mock_run.side_effect = FileNotFoundError("bird not found")

        with pytest.raises(BirdError) as exc:
            _run_bird_command(["bird", "list-timeline"], {})

        assert exc.value.code == ErrorCode.BIRD_COMMAND_FAILED

    @patch('x_digest.fetch.subprocess.run')
    def test_os_error_raises(self, mock_run):
        """OS error raises BirdError."""
        mock_run.side_effect = OSError("Permission denied")

        with pytest.raises(BirdError) as exc:
            _run_bird_command(["bird", "list-timeline"], {})

        assert exc.value.code == ErrorCode.BIRD_COMMAND_FAILED
        assert "Permission denied" in str(exc.value)

    @patch('x_digest.fetch.subprocess.run')
    def test_empty_output_raises(self, mock_run):
        """Empty stdout raises BirdError."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with pytest.raises(BirdError) as exc:
            _run_bird_command(["bird", "list-timeline"], {})

        assert exc.value.code == ErrorCode.BIRD_JSON_PARSE_ERROR
        assert "empty" in str(exc.value).lower()

    @patch('x_digest.fetch.subprocess.run')
    def test_whitespace_only_output_raises(self, mock_run):
        """Whitespace-only stdout raises BirdError."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="   \n  ",
            stderr=""
        )

        with pytest.raises(BirdError) as exc:
            _run_bird_command(["bird", "list-timeline"], {})

        assert exc.value.code == ErrorCode.BIRD_JSON_PARSE_ERROR

    @patch('x_digest.fetch.subprocess.run')
    def test_env_passed_to_subprocess(self, mock_run):
        """Bird env vars are passed to subprocess."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='[{"id": "123"}]',
            stderr=""
        )

        bird_env = {"AUTH_TOKEN": "abc", "CT0": "def"}
        _run_bird_command(["bird"], bird_env)

        # Check env was passed
        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs
        assert call_kwargs["env"]["AUTH_TOKEN"] == "abc"
        assert call_kwargs["env"]["CT0"] == "def"


# === _build_subprocess_env tests ===

class TestBuildSubprocessEnv:
    """Tests for building subprocess environment."""

    def test_includes_system_env(self):
        """System environment variables are included."""
        result = _build_subprocess_env({})
        assert "PATH" in result

    def test_adds_bird_env(self):
        """Bird env vars are added."""
        bird_env = {"AUTH_TOKEN": "abc", "CT0": "def"}
        result = _build_subprocess_env(bird_env)
        assert result["AUTH_TOKEN"] == "abc"
        assert result["CT0"] == "def"

    def test_bird_env_overrides_system(self):
        """Bird env vars override system vars if present."""
        os.environ["TEST_VAR_FETCH"] = "system"
        try:
            result = _build_subprocess_env({"TEST_VAR_FETCH": "bird"})
            assert result["TEST_VAR_FETCH"] == "bird"
        finally:
            del os.environ["TEST_VAR_FETCH"]


# === _build_bird_command tests ===

class TestBuildBirdCommand:
    """Tests for building bird CLI command."""

    @patch('x_digest.fetch._find_bird_executable')
    @patch('x_digest.fetch._build_base_command')
    def test_includes_list_timeline_args(self, mock_base_cmd, mock_find):
        """Command includes list-timeline, list ID, count, and --json."""
        mock_find.return_value = "/usr/local/bin/bird"
        mock_base_cmd.return_value = ["bird", "--auth-token", "abc", "--ct0", "def"]

        bird_env = {"AUTH_TOKEN": "abc", "CT0": "def"}
        cmd = _build_bird_command("12345", 50, bird_env)

        assert "list-timeline" in cmd
        assert "12345" in cmd
        assert "-n" in cmd
        assert "50" in cmd
        assert "--json" in cmd

    @patch('x_digest.fetch._find_bird_executable')
    def test_bird_not_found_raises(self, mock_find):
        """Missing bird CLI raises BirdError."""
        mock_find.return_value = None

        with pytest.raises(BirdError) as exc:
            _build_bird_command("12345", 50, {})

        assert exc.value.code == ErrorCode.BIRD_COMMAND_FAILED
        assert "not found" in str(exc.value)


# === _build_base_command tests ===

class TestBuildBaseCommand:
    """Tests for building base bird command."""

    @patch('x_digest.fetch._find_runtime')
    def test_js_file_uses_runtime(self, mock_runtime):
        """JS file path gets runtime prepended."""
        mock_runtime.return_value = "/usr/local/bin/bun"
        bird_env = {"AUTH_TOKEN": "abc", "CT0": "def"}

        cmd = _build_base_command("/path/to/bird/cli.js", bird_env)

        assert cmd[0] == "/usr/local/bin/bun"
        assert cmd[1] == "/path/to/bird/cli.js"
        assert "--auth-token" in cmd
        assert "abc" in cmd
        assert "--ct0" in cmd
        assert "def" in cmd

    @patch('x_digest.fetch._find_runtime')
    def test_js_file_no_runtime_raises(self, mock_runtime):
        """JS file without runtime available raises BirdError."""
        mock_runtime.return_value = None
        bird_env = {"AUTH_TOKEN": "abc", "CT0": "def"}

        with pytest.raises(BirdError) as exc:
            _build_base_command("/path/to/bird/cli.js", bird_env)

        assert exc.value.code == ErrorCode.BIRD_COMMAND_FAILED
        assert "runtime" in str(exc.value).lower()

    def test_binary_uses_direct_path(self, tmp_path):
        """Binary file (non-JS) is used directly."""
        bird_bin = tmp_path / "bird"
        bird_bin.write_text("#!/bin/bash\necho 'hello'")
        bird_env = {"AUTH_TOKEN": "abc", "CT0": "def"}

        cmd = _build_base_command(str(bird_bin), bird_env)

        assert cmd[0] == str(bird_bin)
        assert "--auth-token" in cmd
        assert "abc" in cmd

    def test_auth_tokens_included(self, tmp_path):
        """Auth tokens are always included in command."""
        bird_bin = tmp_path / "bird"
        bird_bin.write_text("#!/bin/bash\necho 'hello'")
        bird_env = {"AUTH_TOKEN": "token123", "CT0": "ct0_456"}

        cmd = _build_base_command(str(bird_bin), bird_env)

        # Find the index of --auth-token
        auth_idx = cmd.index("--auth-token")
        assert cmd[auth_idx + 1] == "token123"

        ct0_idx = cmd.index("--ct0")
        assert cmd[ct0_idx + 1] == "ct0_456"


# === fetch_tweets_from_bird integration tests (mocked subprocess) ===

class TestFetchTweetsFromBird:
    """Integration tests for fetch_tweets_from_bird with mocked subprocess."""

    @patch('x_digest.fetch._run_bird_command')
    @patch('x_digest.fetch._build_bird_command')
    @patch('x_digest.fetch._load_bird_env')
    def test_full_fetch_pipeline(self, mock_load_env, mock_build_cmd, mock_run):
        """Full fetch pipeline parses tweets and filters by time."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_build_cmd.return_value = ["bird", "list-timeline"]

        tweet_data = [
            make_tweet_json(id="1", createdAt="Wed Feb 04 19:00:43 +0000 2026"),
            make_tweet_json(id="2", createdAt="Wed Feb 04 17:00:00 +0000 2026"),
        ]
        mock_run.return_value = json.dumps(tweet_data)

        since = datetime(2026, 2, 4, 18, 0, tzinfo=UTC)
        tweets = fetch_tweets_from_bird("12345", since)

        assert len(tweets) == 1
        assert tweets[0].id == "1"

    @patch('x_digest.fetch._run_bird_command')
    @patch('x_digest.fetch._build_bird_command')
    @patch('x_digest.fetch._load_bird_env')
    def test_empty_result(self, mock_load_env, mock_build_cmd, mock_run):
        """Empty bird output returns empty list."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_build_cmd.return_value = ["bird"]
        mock_run.return_value = "[]"

        since = datetime(2026, 2, 4, 0, 0, tzinfo=UTC)
        tweets = fetch_tweets_from_bird("12345", since)

        assert tweets == []

    @patch('x_digest.fetch._run_bird_command')
    @patch('x_digest.fetch._build_bird_command')
    @patch('x_digest.fetch._load_bird_env')
    def test_uses_fixture_data(self, mock_load_env, mock_build_cmd, mock_run):
        """Fetch works with real fixture data."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_build_cmd.return_value = ["bird"]

        fixture = load_fixture("single_tweet.json")
        mock_run.return_value = json.dumps(fixture)

        # Use very old since to include all tweets
        since = datetime(2020, 1, 1, tzinfo=UTC)
        tweets = fetch_tweets_from_bird("12345", since)

        assert len(tweets) == 1
        assert tweets[0].id == "2019123973615939775"
        assert tweets[0].author.username == "devlead"

    @patch('x_digest.fetch._run_bird_command')
    @patch('x_digest.fetch._build_bird_command')
    @patch('x_digest.fetch._load_bird_env')
    def test_custom_env_path(self, mock_load_env, mock_build_cmd, mock_run):
        """Custom env path is passed through."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_build_cmd.return_value = ["bird"]
        mock_run.return_value = "[]"

        since = datetime(2020, 1, 1, tzinfo=UTC)
        fetch_tweets_from_bird("12345", since, env_path="/custom/path/env")

        mock_load_env.assert_called_once_with("/custom/path/env")

    @patch('x_digest.fetch._run_bird_command')
    @patch('x_digest.fetch._build_bird_command')
    @patch('x_digest.fetch._load_bird_env')
    def test_custom_count(self, mock_load_env, mock_build_cmd, mock_run):
        """Custom count is passed to build command."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_build_cmd.return_value = ["bird"]
        mock_run.return_value = "[]"

        since = datetime(2020, 1, 1, tzinfo=UTC)
        fetch_tweets_from_bird("12345", since, count=100)

        mock_build_cmd.assert_called_once_with("12345", 100, {"AUTH_TOKEN": "abc", "CT0": "def"})

    @patch('x_digest.fetch._load_bird_env')
    def test_env_error_propagates(self, mock_load_env):
        """BirdError from env loading propagates."""
        mock_load_env.side_effect = BirdError(ErrorCode.BIRD_AUTH_FAILED)

        since = datetime(2020, 1, 1, tzinfo=UTC)
        with pytest.raises(BirdError) as exc:
            fetch_tweets_from_bird("12345", since)

        assert exc.value.code == ErrorCode.BIRD_AUTH_FAILED

    @patch('x_digest.fetch._run_bird_command')
    @patch('x_digest.fetch._build_bird_command')
    @patch('x_digest.fetch._load_bird_env')
    def test_invalid_json_from_bird_raises(self, mock_load_env, mock_build_cmd, mock_run):
        """Invalid JSON from bird raises BirdError."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_build_cmd.return_value = ["bird"]
        mock_run.return_value = "not valid json"

        since = datetime(2020, 1, 1, tzinfo=UTC)
        with pytest.raises(BirdError) as exc:
            fetch_tweets_from_bird("12345", since)

        assert exc.value.code == ErrorCode.BIRD_JSON_PARSE_ERROR


# === check_bird_auth tests ===

class TestCheckBirdAuth:
    """Tests for bird authentication check."""

    @patch('x_digest.fetch.subprocess.run')
    @patch('x_digest.fetch._find_bird_executable')
    @patch('x_digest.fetch._load_bird_env')
    def test_auth_success(self, mock_load_env, mock_find, mock_run):
        """Successful auth check returns True."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_find.return_value = "/usr/local/bin/bird"
        mock_run.return_value = Mock(returncode=0, stdout="@testuser")

        result = check_bird_auth()
        assert result is True

    @patch('x_digest.fetch.subprocess.run')
    @patch('x_digest.fetch._find_bird_executable')
    @patch('x_digest.fetch._load_bird_env')
    def test_auth_failure(self, mock_load_env, mock_find, mock_run):
        """Failed auth check returns False."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_find.return_value = "/usr/local/bin/bird"
        mock_run.return_value = Mock(returncode=1, stderr="Unauthorized")

        result = check_bird_auth()
        assert result is False

    @patch('x_digest.fetch._load_bird_env')
    def test_env_error_returns_false(self, mock_load_env):
        """Env loading error returns False."""
        mock_load_env.side_effect = BirdError(ErrorCode.BIRD_AUTH_FAILED)

        result = check_bird_auth()
        assert result is False

    @patch('x_digest.fetch._find_bird_executable')
    @patch('x_digest.fetch._load_bird_env')
    def test_bird_not_found_returns_false(self, mock_load_env, mock_find):
        """Bird not found returns False."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_find.return_value = None

        result = check_bird_auth()
        assert result is False

    @patch('x_digest.fetch.subprocess.run')
    @patch('x_digest.fetch._find_bird_executable')
    @patch('x_digest.fetch._load_bird_env')
    def test_timeout_returns_false(self, mock_load_env, mock_find, mock_run):
        """Timeout during auth check returns False."""
        mock_load_env.return_value = {"AUTH_TOKEN": "abc", "CT0": "def"}
        mock_find.return_value = "/usr/local/bin/bird"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bird", timeout=30)

        result = check_bird_auth()
        assert result is False

    def test_custom_env_path(self, tmp_path):
        """Custom env path is used."""
        env_file = tmp_path / "env"
        env_file.write_text(
            'export AUTH_TOKEN="abc"\n'
            'export CT0="def"\n'
        )

        with patch('x_digest.fetch._find_bird_executable') as mock_find:
            mock_find.return_value = None
            result = check_bird_auth(str(env_file))
            assert result is False  # Bird not found, but env loaded


# === Default values tests ===

class TestDefaults:
    """Tests for default configuration values."""

    def test_default_env_path(self):
        """Default bird env path is ~/.config/bird/env."""
        assert "bird/env" in DEFAULT_BIRD_ENV_PATH

    def test_default_fetch_count(self):
        """Default fetch count is 50."""
        assert DEFAULT_FETCH_COUNT == 50

    def test_timeout_is_reasonable(self):
        """Timeout is set to 30 seconds."""
        assert BIRD_TIMEOUT_SECONDS == 30

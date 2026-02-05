"""
Twitter data fetching using bird CLI.

Integrates with the bird CLI to fetch tweets from Twitter lists.
Handles authentication, rate limiting, error mapping, and JSON parsing.

The fetch module abstracts the bird CLI interface and provides structured
error handling with proper error code mapping for monitoring.
"""

import subprocess
import json
import os
import re
import shutil
from typing import List, Dict, Optional
from datetime import datetime, UTC

from .models import Tweet, parse_tweets
from .errors import BirdError, ErrorCode
from .utils import parse_twitter_date


# Default configuration
DEFAULT_BIRD_ENV_PATH = os.path.expanduser("~/.config/bird/env")
DEFAULT_FETCH_COUNT = 50
BIRD_TIMEOUT_SECONDS = 30


def fetch_tweets_from_bird(
    list_id: str,
    since: datetime,
    env_path: Optional[str] = None,
    count: int = DEFAULT_FETCH_COUNT
) -> List[Tweet]:
    """
    Fetch tweets from Twitter list using bird CLI.

    Args:
        list_id: Twitter list ID or URL
        since: Fetch tweets since this timestamp
        env_path: Path to bird environment file
        count: Number of tweets to fetch

    Returns:
        List of Tweet objects filtered by since timestamp

    Raises:
        BirdError: If bird CLI fails or returns invalid data
    """
    if env_path is None:
        env_path = DEFAULT_BIRD_ENV_PATH

    # Load bird auth from environment file
    bird_env = _load_bird_env(env_path)

    # Build and execute bird command
    cmd = _build_bird_command(list_id, count, bird_env)
    stdout = _run_bird_command(cmd, bird_env)

    # Parse JSON output to Tweet objects
    tweets = parse_tweets(stdout)

    # Filter by since timestamp
    filtered = _filter_tweets_by_time(tweets, since)

    return filtered


def check_bird_auth(env_path: Optional[str] = None) -> bool:
    """
    Check if bird CLI authentication is working.

    Runs 'bird whoami' to verify auth tokens are valid.

    Args:
        env_path: Path to bird environment file

    Returns:
        True if authentication works, False otherwise
    """
    if env_path is None:
        env_path = DEFAULT_BIRD_ENV_PATH

    try:
        bird_env = _load_bird_env(env_path)
    except BirdError:
        return False

    bird_path = _find_bird_executable()
    if bird_path is None:
        return False

    try:
        cmd = _build_base_command(bird_path, bird_env) + ["whoami"]
        env = _build_subprocess_env(bird_env)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BIRD_TIMEOUT_SECONDS,
            env=env
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _load_bird_env(env_path: str) -> Dict[str, str]:
    """
    Load bird environment variables from env file.

    Parses 'export VAR=value' and 'export VAR="value"' lines.

    Args:
        env_path: Path to bird env file

    Returns:
        Dictionary of environment variables

    Raises:
        BirdError: If env file not found or missing required variables
    """
    env_path = os.path.expanduser(env_path)

    if not os.path.exists(env_path):
        raise BirdError(
            ErrorCode.BIRD_AUTH_FAILED,
            f"Bird env file not found: {env_path}"
        )

    env_vars = {}

    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Remove 'export ' prefix
                if line.startswith('export '):
                    line = line[7:]

                # Parse KEY=VALUE or KEY="VALUE"
                match = re.match(r'^(\w+)=(.*)$', line)
                if match:
                    key = match.group(1)
                    value = match.group(2).strip()
                    # Remove surrounding quotes
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    env_vars[key] = value
    except PermissionError:
        raise BirdError(
            ErrorCode.BIRD_AUTH_FAILED,
            f"Permission denied reading: {env_path}"
        )

    # Validate required auth variables
    auth_token = env_vars.get('AUTH_TOKEN') or env_vars.get('TWITTER_AUTH_TOKEN')
    ct0 = env_vars.get('CT0') or env_vars.get('TWITTER_CT0')

    if not auth_token or not ct0:
        raise BirdError(
            ErrorCode.BIRD_AUTH_FAILED,
            "Missing AUTH_TOKEN or CT0 in bird env file"
        )

    # Normalize to standard keys
    env_vars['AUTH_TOKEN'] = auth_token
    env_vars['CT0'] = ct0

    return env_vars


def _find_bird_executable() -> Optional[str]:
    """
    Find the bird CLI executable.

    Checks multiple locations and returns the path to bird CLI script.

    Returns:
        Path to bird executable, or None if not found
    """
    # Check if bird is in PATH
    bird_path = shutil.which('bird')
    if bird_path:
        return bird_path

    # Check common bun global install location
    bun_bird = os.path.expanduser(
        "~/.bun/install/global/node_modules/@steipete/bird/dist/cli.js"
    )
    if os.path.exists(bun_bird):
        return bun_bird

    # Check root's bun location (for VPS setups)
    root_bun_bird = "/root/.bun/install/global/node_modules/@steipete/bird/dist/cli.js"
    if os.path.exists(root_bun_bird):
        return root_bun_bird

    return None


def _find_runtime() -> Optional[str]:
    """
    Find a JavaScript runtime (bun or node) for executing bird CLI.

    Returns:
        Path to runtime executable, or None if not found
    """
    # Try bun first (faster startup)
    for runtime in ['bun', 'node']:
        path = shutil.which(runtime)
        if path:
            return path

    # Check common locations
    for path in ['/root/.bun/bin/bun', '/usr/local/bin/bun',
                 '/usr/local/bin/node', '/usr/bin/node']:
        if os.path.exists(path):
            return path

    return None


def _build_base_command(bird_path: str, bird_env: Dict[str, str]) -> List[str]:
    """
    Build the base command for running bird CLI.

    Handles the case where bird needs to be run via bun/node runtime.

    Args:
        bird_path: Path to bird executable/script
        bird_env: Bird environment variables with auth tokens

    Returns:
        List of command components
    """
    cmd = []

    # If bird_path is a .js file, we need a runtime
    if bird_path.endswith('.js'):
        runtime = _find_runtime()
        if runtime is None:
            raise BirdError(
                ErrorCode.BIRD_COMMAND_FAILED,
                "No JavaScript runtime (bun/node) found to run bird CLI"
            )
        cmd.append(runtime)
        cmd.append(bird_path)
    else:
        # Check if the shebang uses node but node isn't available
        # In that case, run with bun explicitly
        try:
            with open(bird_path, 'r') as f:
                first_line = f.readline()
            if 'node' in first_line and not shutil.which('node'):
                runtime = _find_runtime()
                if runtime:
                    cmd.append(runtime)
                    cmd.append(bird_path)
                else:
                    raise BirdError(
                        ErrorCode.BIRD_COMMAND_FAILED,
                        "bird requires node/bun runtime which is not available"
                    )
            else:
                cmd.append(bird_path)
        except (OSError, UnicodeDecodeError):
            cmd.append(bird_path)

    # Add auth tokens
    auth_token = bird_env.get('AUTH_TOKEN', '')
    ct0 = bird_env.get('CT0', '')

    if auth_token:
        cmd.extend(['--auth-token', auth_token])
    if ct0:
        cmd.extend(['--ct0', ct0])

    return cmd


def _build_bird_command(
    list_id: str,
    count: int,
    bird_env: Dict[str, str]
) -> List[str]:
    """
    Build the full bird CLI command for fetching list timeline.

    Args:
        list_id: Twitter list ID or URL
        count: Number of tweets to fetch
        bird_env: Bird environment variables

    Returns:
        List of command components

    Raises:
        BirdError: If bird executable not found
    """
    bird_path = _find_bird_executable()
    if bird_path is None:
        raise BirdError(
            ErrorCode.BIRD_COMMAND_FAILED,
            "bird CLI not found. Install with: bun install -g @steipete/bird"
        )

    cmd = _build_base_command(bird_path, bird_env)
    cmd.extend([
        'list-timeline',
        str(list_id),
        '-n', str(count),
        '--json'
    ])

    return cmd


def _build_subprocess_env(bird_env: Dict[str, str]) -> Dict[str, str]:
    """
    Build environment dictionary for subprocess execution.

    Starts with current environment and adds bird env vars.

    Args:
        bird_env: Bird environment variables

    Returns:
        Complete environment dictionary for subprocess
    """
    env = os.environ.copy()
    env.update(bird_env)
    return env


def _run_bird_command(cmd: List[str], bird_env: Dict[str, str]) -> str:
    """
    Execute bird CLI command and return stdout.

    Args:
        cmd: Command to execute as list of strings
        bird_env: Bird environment variables

    Returns:
        stdout from the command

    Raises:
        BirdError: If command fails, times out, or returns invalid output
    """
    env = _build_subprocess_env(bird_env)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BIRD_TIMEOUT_SECONDS,
            env=env
        )

        if result.returncode != 0:
            raise _map_bird_error(result.stderr, result.returncode)

        stdout = result.stdout.strip()

        if not stdout:
            raise BirdError(
                ErrorCode.BIRD_JSON_PARSE_ERROR,
                "bird CLI returned empty output"
            )

        return stdout

    except subprocess.TimeoutExpired:
        raise BirdError(
            ErrorCode.BIRD_NETWORK_ERROR,
            f"bird CLI timed out after {BIRD_TIMEOUT_SECONDS}s"
        )
    except FileNotFoundError:
        raise BirdError(
            ErrorCode.BIRD_COMMAND_FAILED,
            "bird CLI executable not found"
        )
    except OSError as e:
        raise BirdError(
            ErrorCode.BIRD_COMMAND_FAILED,
            f"Failed to execute bird CLI: {str(e)}"
        )


def _filter_tweets_by_time(tweets: List[Tweet], since: datetime) -> List[Tweet]:
    """
    Filter tweets to only include those after the since timestamp.

    Args:
        tweets: List of Tweet objects
        since: Minimum timestamp (inclusive)

    Returns:
        Filtered list of tweets
    """
    # Ensure since is timezone-aware
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)

    filtered = []
    for tweet in tweets:
        tweet_time = parse_twitter_date(tweet.created_at)
        if tweet_time >= since:
            filtered.append(tweet)

    return filtered


def _map_bird_error(stderr: str, return_code: int) -> BirdError:
    """
    Map bird CLI error output to appropriate BirdError.

    Analyzes stderr text to determine the specific error type and
    maps it to the correct ErrorCode for monitoring.

    Args:
        stderr: Standard error output from bird CLI
        return_code: Process exit code

    Returns:
        BirdError with appropriate error code
    """
    stderr_lower = stderr.lower() if stderr else ""

    # Rate limiting (check first - specific)
    if any(term in stderr_lower for term in [
        'rate limit', '429', 'too many requests'
    ]):
        return BirdError(ErrorCode.BIRD_RATE_LIMITED)

    # JSON parsing errors (check before auth - "token" appears in JSON errors too)
    if any(term in stderr_lower for term in [
        'json', 'parse error', 'syntaxerror', 'unexpected token'
    ]):
        return BirdError(ErrorCode.BIRD_JSON_PARSE_ERROR)

    # Network errors
    if any(term in stderr_lower for term in [
        'network', 'timeout', 'econnrefused', 'enotfound',
        'econnreset', 'socket', 'dns'
    ]):
        return BirdError(ErrorCode.BIRD_NETWORK_ERROR)

    # Authentication errors
    if any(term in stderr_lower for term in [
        'unauthorized', 'auth', '401', 'forbidden', '403',
        'cookie', 'login'
    ]):
        return BirdError(ErrorCode.BIRD_AUTH_FAILED)

    # Invalid list ID
    if any(term in stderr_lower for term in [
        'not found', 'invalid list', 'list not accessible'
    ]):
        return BirdError(ErrorCode.BIRD_INVALID_LIST_ID)

    # Generic command failure
    return BirdError(
        ErrorCode.BIRD_COMMAND_FAILED,
        f"bird CLI exited with code {return_code}"
    )

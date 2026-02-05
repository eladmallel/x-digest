"""
Command line interface for x-digest.

Provides CLI commands for running digests, validation, onboarding, and monitoring.
Supports multiple subcommands:

- run: Execute digest for a specific list
- validate: Validate configuration file
- watch: Run digests on an interval

The CLI handles argument parsing, config file discovery, and orchestrates
the entire digest pipeline from tweet fetching to delivery.
"""

import argparse
import sys
import os
import json
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from . import __version__
from .config import load_config, get_list_config
from .errors import (
    ConfigError, BirdError, LLMError, DeliveryError,
    XDigestError, ErrorCode
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="x-digest",
        description="Twitter List Digest Pipeline — Transform curated Twitter lists into concise digests."
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"x-digest {__version__}"
    )

    # Global options
    parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=None
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run subcommand ---
    run_parser = subparsers.add_parser(
        "run",
        help="Execute digest for a specific list"
    )
    run_parser.add_argument(
        "--list",
        required=True,
        dest="list_name",
        help="Which list from config to run"
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print digest to stdout instead of sending"
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip idempotency check"
    )
    run_parser.add_argument(
        "--preview",
        action="store_true",
        help="Fetch and show tweet count + classification, no LLM call"
    )
    run_parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Override lookback hours (instead of status-based time window)"
    )

    # --- validate subcommand ---
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate configuration file"
    )
    validate_parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=None
    )

    # --- watch subcommand ---
    watch_parser = subparsers.add_parser(
        "watch",
        help="Run digests on an interval"
    )
    watch_parser.add_argument(
        "--list",
        required=True,
        dest="list_name",
        help="Which list to watch"
    )
    watch_parser.add_argument(
        "--every",
        required=True,
        help="Interval (e.g. 12h, 30m)"
    )

    args = parser.parse_args(argv)

    # Show help if no command given
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    return args


def find_config_file(config_path: Optional[str] = None) -> str:
    """
    Find config file in search order.

    Args:
        config_path: Explicit path from --config flag

    Returns:
        Path to config file

    Raises:
        ConfigError: If no config file found
    """
    if config_path:
        if os.path.exists(config_path):
            return config_path
        raise ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)

    search_paths = [
        "./x-digest-config.json",
        "./config/x-digest-config.json",
        os.path.expanduser("~/.config/x-digest/config.json")
    ]

    for path in search_paths:
        if os.path.exists(path):
            return path

    raise ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)


def _load_env():
    """Load .env file using python-dotenv if available."""
    try:
        from dotenv import load_dotenv

        # Search for .env in current directory and parent directories
        env_paths = [
            ".env",
            os.path.join(os.path.dirname(__file__), '..', '..', '.env'),
        ]

        for env_path in env_paths:
            expanded = os.path.abspath(env_path)
            if os.path.exists(expanded):
                load_dotenv(expanded)
                return
    except ImportError:
        pass  # python-dotenv not installed, rely on system env


def run_pipeline(
    list_name: str,
    config: Dict[str, Any],
    dry_run: bool = False,
    force: bool = False,
    preview: bool = False,
    hours: Optional[float] = None
) -> bool:
    """
    Execute the full digest pipeline for a named list.

    Pipeline order: fetch → classify → pre-summarize → build images →
    generate digest → deliver (or print if dry-run)

    Args:
        list_name: Which list from config to run
        config: Loaded configuration dictionary
        dry_run: Print digest to stdout instead of sending
        force: Skip idempotency check
        preview: Just show stats, no LLM call
        hours: Override lookback hours

    Returns:
        True if pipeline completed successfully
    """
    from .fetch import fetch_tweets_from_bird
    from .classify import categorize_tweets, dedupe_quotes, get_thread_stats, reconstruct_threads
    from .presummary import presummary_tweets
    from .images import prioritize_images, get_image_stats
    from .digest import generate_digest, split_digest
    from .delivery.base import get_provider, send_digest
    from .status import load_status, update_status, should_run, get_time_window
    from .llm.gemini import GeminiProvider

    # Get list-specific config
    list_config = get_list_config(config, list_name)
    display_name = list_config.get("display_name", list_name)
    emoji = list_config.get("emoji", "📋")

    # Determine status file path
    data_dir = os.path.join(os.getcwd(), "data")
    status_path = os.path.join(data_dir, "status.json")

    # Check idempotency
    if not force:
        status = load_status(status_path)
        window = config.get("idempotency_window_minutes", 30)
        if not should_run(list_name, status, window_minutes=window):
            print(f"⏭  Skipping {display_name}: ran recently (use --force to override)")
            return True

    # Determine time window
    status = load_status(status_path)
    if hours is not None:
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)
    else:
        start_time, end_time = get_time_window(list_name, status)

    print(f"\n{emoji} {display_name} Digest Pipeline")
    print(f"   Time window: {start_time.strftime('%Y-%m-%d %H:%M')} → {end_time.strftime('%Y-%m-%d %H:%M')} UTC")

    # --- Step 1: Fetch ---
    print("\n📡 Fetching tweets...")

    bird_env_path = os.environ.get("BIRD_ENV_PATH", None)
    tweets = fetch_tweets_from_bird(
        list_id=list_config["id"],
        since=start_time,
        env_path=bird_env_path
    )

    print(f"   Found {len(tweets)} tweets since {start_time.strftime('%Y-%m-%d %H:%M')} UTC")

    # Update status with fetch count
    update_status(status_path, list_name,
                  last_run=datetime.now(UTC).isoformat(),
                  tweets_fetched=len(tweets))

    if len(tweets) == 0:
        print("   📭 No tweets found in time window")
        if not preview:
            # Generate empty digest
            digest_config = {**list_config, "list_name": list_name}
            from .digest import format_empty_digest
            digest_text = format_empty_digest(list_name, digest_config)
            if dry_run:
                print(f"\n--- Digest (dry-run) ---\n{digest_text}\n---")
            else:
                _deliver_digest(digest_text, config, list_config)
            update_status(status_path, list_name,
                          last_success=datetime.now(UTC).isoformat(),
                          error_code=None)
        return True

    # --- Step 2: Classify ---
    print("\n🏷️  Classifying tweets...")
    deduped = dedupe_quotes(tweets)
    categories = categorize_tweets(deduped)
    threads = reconstruct_threads(deduped)
    thread_stats = get_thread_stats(threads)

    print(f"   Standalone: {len(categories['standalone'])}")
    print(f"   Threads: {len(categories['threads'])} ({thread_stats['multi_tweet_threads']} multi-tweet)")
    print(f"   Quotes: {len(categories['quotes'])}")
    print(f"   Replies: {len(categories['replies'])}")
    print(f"   Retweets: {len(categories['retweets'])}")

    if len(deduped) < len(tweets):
        print(f"   Deduped: {len(tweets) - len(deduped)} quoted tweets removed")

    # --- Step 3: Image stats ---
    image_stats = get_image_stats(deduped)
    print(f"\n🖼️  Images: {image_stats['total_images']} photos, {image_stats['total_videos']} videos")
    print(f"   Tweets with media: {image_stats['tweets_with_media']}")

    if preview:
        print(f"\n✅ Preview complete — {len(deduped)} tweets ready for digest")
        return True

    # --- Step 4: Pre-summarize ---
    print("\n📝 Pre-summarizing long content...")
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise LLMError(ErrorCode.LLM_API_AUTH, "GEMINI_API_KEY not set in environment")

    llm_config = config.get("defaults", {}).get("llm", {})
    model = llm_config.get("model", "gemini-2.0-flash")
    llm_provider = GeminiProvider(api_key=gemini_api_key, model=model)

    presummary_config = config.get("defaults", {})
    tweet_summaries = presummary_tweets(deduped, llm_provider, presummary_config)

    # Build summaries dict
    summaries: Dict[str, str] = {}
    for tweet, summary in tweet_summaries:
        if summary is not None:
            summaries[tweet.id] = summary

    pre_summarized_count = len(summaries)
    print(f"   Pre-summarized: {pre_summarized_count} items")

    # --- Step 5: Build images ---
    print("\n🖼️  Selecting images for digest...")
    selected_images = prioritize_images(deduped)
    print(f"   Selected: {len(selected_images)} images for multimodal digest")

    # --- Step 6: Generate digest ---
    print("\n🤖 Generating digest...")
    digest_config = {
        **list_config,
        "list_name": list_name,
        "defaults": config.get("defaults", {})
    }

    digest_text = generate_digest(
        deduped,
        summaries,
        selected_images,
        digest_config,
        llm_provider
    )

    print(f"   Digest length: {len(digest_text)} chars")

    # --- Step 7: Deliver ---
    if dry_run:
        print(f"\n--- Digest (dry-run) ---\n{digest_text}\n---")
        update_status(status_path, list_name,
                      last_success=datetime.now(UTC).isoformat(),
                      error_code=None,
                      digest_sent=False)
        return True

    print("\n📤 Delivering digest...")
    success = _deliver_digest(digest_text, config, list_config)

    if success:
        print("   ✅ Digest delivered successfully")
        update_status(status_path, list_name,
                      last_success=datetime.now(UTC).isoformat(),
                      error_code=None,
                      digest_sent=True)
    else:
        print("   ❌ Delivery failed")
        update_status(status_path, list_name,
                      error_code=ErrorCode.DELIVERY_SEND_FAILED.value)

    return success


def _deliver_digest(
    digest_text: str,
    config: Dict[str, Any],
    list_config: Dict[str, Any]
) -> bool:
    """
    Deliver digest via configured delivery provider.

    Args:
        digest_text: The digest text to send
        config: Full config dictionary
        list_config: List-specific config

    Returns:
        True if delivery was successful
    """
    from .digest import split_digest
    from .delivery.base import get_provider, send_digest

    delivery_config = config.get("delivery", {})

    # Override with environment variables if set
    if os.environ.get("WHATSAPP_GATEWAY"):
        delivery_config.setdefault("provider", "whatsapp")
        delivery_config.setdefault("whatsapp", {})
        delivery_config["whatsapp"]["gateway_url"] = os.environ["WHATSAPP_GATEWAY"]

    if os.environ.get("WHATSAPP_RECIPIENT"):
        delivery_config.setdefault("whatsapp", {})
        delivery_config["whatsapp"]["recipient"] = os.environ["WHATSAPP_RECIPIENT"]

    provider = get_provider(delivery_config)
    recipient = delivery_config.get("whatsapp", {}).get("recipient", "") or \
                delivery_config.get("telegram", {}).get("chat_id", "")

    # Split digest if too long
    parts = split_digest(digest_text)
    print(f"   Sending {len(parts)} message(s)...")

    retry_config = config.get("retry", {})
    max_retries = retry_config.get("max_attempts", 3)

    return send_digest(parts, provider, recipient, max_retries=max_retries)


def cmd_run(args: argparse.Namespace) -> int:
    """
    Handle the 'run' subcommand.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    _load_env()

    try:
        config_path = find_config_file(args.config)
        config = load_config(config_path)
    except ConfigError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        return 1

    try:
        success = run_pipeline(
            list_name=args.list_name,
            config=config,
            dry_run=args.dry_run,
            force=args.force,
            preview=args.preview,
            hours=args.hours
        )
        return 0 if success else 1

    except BirdError as e:
        print(f"\n❌ Tweet fetch error: {e}", file=sys.stderr)
        return 1
    except LLMError as e:
        print(f"\n❌ LLM error: {e}", file=sys.stderr)
        return 1
    except DeliveryError as e:
        print(f"\n❌ Delivery error: {e}", file=sys.stderr)
        return 1
    except XDigestError as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    """
    Handle the 'validate' subcommand.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        config_path = find_config_file(args.config)
        config = load_config(config_path)
    except ConfigError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        return 1

    print(f"✅ Configuration valid: {config_path}")

    # Show summary
    lists = config.get("lists", {})
    print(f"\n   Lists: {len(lists)}")
    for name, list_cfg in lists.items():
        enabled = list_cfg.get("enabled", True)
        display = list_cfg.get("display_name", name.title())
        emoji = list_cfg.get("emoji", "📋")
        status_str = "✓" if enabled else "✗ (disabled)"
        print(f"   {status_str} {emoji} {display} (id: {list_cfg['id']})")

    schedules = config.get("schedules", [])
    if schedules:
        print(f"\n   Schedules: {len(schedules)}")
        for sched in schedules:
            print(f"   - {sched['name']}: {sched.get('cron', 'N/A')} ({sched.get('description', '')})")

    delivery = config.get("delivery", {})
    provider = delivery.get("provider", "not configured")
    print(f"\n   Delivery: {provider}")

    return 0


def main():
    """Main CLI entry point."""
    try:
        args = parse_args()

        if args.command == "run":
            exit_code = cmd_run(args)
        elif args.command == "validate":
            exit_code = cmd_validate(args)
        elif args.command == "watch":
            _load_env()
            from .watch import parse_interval
            interval = parse_interval(args.every)
            print(f"Watch mode not yet fully implemented (interval: {interval}s)")
            exit_code = 0
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            exit_code = 1

        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

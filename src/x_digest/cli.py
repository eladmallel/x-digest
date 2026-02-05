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
from .logging import setup_logging, get_logger


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
    run_parser.add_argument(
        "--no-artifacts",
        action="store_true",
        help="Skip saving pipeline artifacts to data/digests/"
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

    # --- crontab subcommand ---
    crontab_parser = subparsers.add_parser(
        "crontab",
        help="Generate crontab entries from config schedules"
    )
    crontab_parser.add_argument(
        "--config",
        help="Path to configuration file",
        default=None
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
    hours: Optional[float] = None,
    no_artifacts: bool = False
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
        no_artifacts: Skip saving pipeline artifacts

    Returns:
        True if pipeline completed successfully
    """
    import time as _time
    from .fetch import fetch_tweets_from_bird
    from .classify import categorize_tweets, dedupe_quotes, get_thread_stats, reconstruct_threads
    from .presummary import presummary_tweets
    from .images import prioritize_images, get_image_stats
    from .digest import generate_digest, split_digest, build_digest_payload, build_system_prompt
    from .delivery.base import get_provider, send_digest
    from .status import load_status, update_status, should_run, get_time_window, write_meta
    from .llm.gemini import GeminiProvider
    from .artifacts import save_artifacts

    logger = get_logger("pipeline")
    pipeline_start = _time.time()

    # Get list-specific config
    list_config = get_list_config(config, list_name)
    display_name = list_config.get("display_name", list_name)
    emoji = list_config.get("emoji", "📋")

    # Determine status file path
    data_dir = os.path.join(os.getcwd(), "data")
    status_path = os.path.join(data_dir, "status.json")

    logger.info("Starting pipeline for list '%s' (%s)", list_name, display_name)

    # Check idempotency
    if not force:
        status = load_status(status_path)
        window = config.get("idempotency_window_minutes", 30)
        if not should_run(list_name, status, window_minutes=window):
            logger.info("Skipping %s: ran recently (within %d min window)", list_name, window)
            print(f"⏭  Skipping {display_name}: ran recently (use --force to override)")
            return True

    # Determine time window
    status = load_status(status_path)
    if hours is not None:
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)
    else:
        start_time, end_time = get_time_window(list_name, status)

    logger.info("Time window: %s → %s", start_time.isoformat(), end_time.isoformat())
    print(f"\n{emoji} {display_name} Digest Pipeline")
    print(f"   Time window: {start_time.strftime('%Y-%m-%d %H:%M')} → {end_time.strftime('%Y-%m-%d %H:%M')} UTC")

    # --- Step 1: Fetch ---
    print("\n📡 Fetching tweets...")
    logger.info("Fetching tweets for list '%s'", list_name)
    fetch_start = _time.time()

    bird_env_path = os.environ.get("BIRD_ENV_PATH", None)
    tweets = fetch_tweets_from_bird(
        list_id=list_config["id"],
        since=start_time,
        env_path=bird_env_path
    )

    fetch_ms = int((_time.time() - fetch_start) * 1000)
    logger.info("Fetched %d tweets in %dms", len(tweets), fetch_ms)
    print(f"   Found {len(tweets)} tweets since {start_time.strftime('%Y-%m-%d %H:%M')} UTC")

    # Update status with fetch count
    update_status(status_path, list_name,
                  last_run=datetime.now(UTC).isoformat(),
                  tweets_fetched=len(tweets))

    if len(tweets) == 0:
        logger.info("No tweets found in time window for '%s'", list_name)
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
    logger.info("Classifying %d tweets", len(tweets))
    classify_start = _time.time()
    deduped = dedupe_quotes(tweets)
    categories = categorize_tweets(deduped)
    threads = reconstruct_threads(deduped)
    thread_stats = get_thread_stats(threads)
    classify_ms = int((_time.time() - classify_start) * 1000)

    logger.info("Classification: %d standalone, %d threads, %d quotes, %d replies, %d retweets (%dms)",
                len(categories['standalone']), len(categories['threads']),
                len(categories['quotes']), len(categories['replies']),
                len(categories['retweets']), classify_ms)

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
        logger.info("Preview complete for '%s': %d tweets ready", list_name, len(deduped))
        print(f"\n✅ Preview complete — {len(deduped)} tweets ready for digest")
        return True

    # --- Step 4: Pre-summarize ---
    print("\n📝 Pre-summarizing long content...")
    logger.info("Starting pre-summarization")
    presummary_start = _time.time()
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
    presummary_ms = int((_time.time() - presummary_start) * 1000)
    logger.info("Pre-summarized %d items in %dms", pre_summarized_count, presummary_ms)
    print(f"   Pre-summarized: {pre_summarized_count} items")

    # --- Step 5: Build images ---
    print("\n🖼️  Selecting images for digest...")
    selected_images = prioritize_images(deduped)
    logger.info("Selected %d images for digest", len(selected_images))
    print(f"   Selected: {len(selected_images)} images for multimodal digest")

    # --- Step 6: Generate digest ---
    print("\n🤖 Generating digest...")
    logger.info("Generating digest")
    digest_start = _time.time()
    digest_config = {
        **list_config,
        "list_name": list_name,
        "defaults": config.get("defaults", {})
    }

    # Build the payload (for artifact saving)
    payload_text = build_digest_payload(deduped, summaries, selected_images, digest_config)
    system_prompt = build_system_prompt(digest_config)

    digest_text = generate_digest(
        deduped,
        summaries,
        selected_images,
        digest_config,
        llm_provider
    )

    digest_ms = int((_time.time() - digest_start) * 1000)
    logger.info("Digest generated: %d chars in %dms", len(digest_text), digest_ms)
    print(f"   Digest length: {len(digest_text)} chars")

    # --- Save artifacts ---
    if not no_artifacts:
        logger.info("Saving pipeline artifacts")
        try:
            _save_pipeline_artifacts(
                data_dir=data_dir,
                list_name=list_name,
                tweets=tweets,
                summaries=summaries,
                payload_text=payload_text,
                system_prompt=system_prompt,
                digest_text=digest_text,
                fetch_ms=fetch_ms,
                presummary_ms=presummary_ms,
                digest_ms=digest_ms,
                pre_summarized_count=pre_summarized_count,
                image_count=len(selected_images),
            )
        except Exception as e:
            logger.warning("Failed to save artifacts: %s", e)

    # --- Step 7: Deliver ---
    if dry_run:
        print(f"\n--- Digest (dry-run) ---\n{digest_text}\n---")
        update_status(status_path, list_name,
                      last_success=datetime.now(UTC).isoformat(),
                      error_code=None,
                      digest_sent=False)
        total_ms = int((_time.time() - pipeline_start) * 1000)
        logger.info("Dry-run complete for '%s' in %dms", list_name, total_ms)
        return True

    print("\n📤 Delivering digest...")
    logger.info("Delivering digest for '%s'", list_name)
    delivery_start = _time.time()
    success = _deliver_digest(digest_text, config, list_config)
    delivery_ms = int((_time.time() - delivery_start) * 1000)

    total_ms = int((_time.time() - pipeline_start) * 1000)

    if success:
        logger.info("Digest delivered successfully for '%s' in %dms (total: %dms)",
                     list_name, delivery_ms, total_ms)
        print("   ✅ Digest delivered successfully")
        update_status(status_path, list_name,
                      last_success=datetime.now(UTC).isoformat(),
                      error_code=None,
                      digest_sent=True)
    else:
        logger.error("Delivery failed for '%s' after %dms", list_name, delivery_ms)
        print("   ❌ Delivery failed")
        update_status(status_path, list_name,
                      error_code=ErrorCode.DELIVERY_SEND_FAILED.value)

    return success


def _save_pipeline_artifacts(
    data_dir: str,
    list_name: str,
    tweets: list,
    summaries: Dict[str, str],
    payload_text: str,
    system_prompt: str,
    digest_text: str,
    fetch_ms: int,
    presummary_ms: int,
    digest_ms: int,
    pre_summarized_count: int,
    image_count: int,
) -> None:
    """Save pipeline artifacts to data/digests/... directory."""
    from .artifacts import save_artifacts

    save_artifacts(
        data_dir=data_dir,
        list_name=list_name,
        tweets=tweets,
        summaries=summaries,
        payload_text=payload_text,
        system_prompt=system_prompt,
        digest_text=digest_text,
        fetch_ms=fetch_ms,
        presummary_ms=presummary_ms,
        digest_ms=digest_ms,
        pre_summarized_count=pre_summarized_count,
        image_count=image_count,
    )


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
            hours=args.hours,
            no_artifacts=getattr(args, 'no_artifacts', False)
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


def generate_crontab(config: Dict[str, Any], config_path: Optional[str] = None) -> str:
    """
    Generate crontab entries from config schedules.

    Args:
        config: Loaded configuration dictionary
        config_path: Path to config file (used in generated commands)

    Returns:
        Valid crontab syntax string
    """
    schedules = config.get("schedules", [])

    if not schedules:
        return "# No schedules defined in config\n"

    lines = [
        "# x-digest crontab — generated from config",
        "# Do not edit manually; regenerate with: x-digest crontab",
        "",
    ]

    # Try to find the x-digest executable
    x_digest_cmd = "python3 -m x_digest"

    config_flag = ""
    if config_path:
        config_flag = f" --config {config_path}"

    for schedule in schedules:
        cron_expr = schedule.get("cron", "")
        list_name = schedule.get("list", "")
        name = schedule.get("name", "")
        description = schedule.get("description", "")

        if not cron_expr or not list_name:
            continue

        # Add comment with description
        if description:
            lines.append(f"# {name}: {description}")
        elif name:
            lines.append(f"# {name}")

        lines.append(f"{cron_expr} {x_digest_cmd}{config_flag} run --list {list_name}")
        lines.append("")

    return "\n".join(lines) + "\n"


def check_crontab_staleness(config_path: str) -> Optional[str]:
    """
    Check if installed crontab may be out of sync with config.

    Args:
        config_path: Path to config file

    Returns:
        Warning message if stale, None otherwise
    """
    import subprocess

    try:
        config_mtime = os.path.getmtime(config_path)
    except OSError:
        return None

    # Check /etc/cron.d/x-digest
    crontab_path = "/etc/cron.d/x-digest"
    if os.path.exists(crontab_path):
        crontab_mtime = os.path.getmtime(crontab_path)
        if config_mtime > crontab_mtime:
            return (
                "Config modified after crontab generation. "
                "Schedules may be out of sync. Run: x-digest crontab"
            )

    # Also check user crontab via `crontab -l`
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and "x-digest" in result.stdout:
            # Can't reliably check mtime of user crontab, just return None
            pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def cmd_crontab(args: argparse.Namespace) -> int:
    """
    Handle the 'crontab' subcommand.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        config_path = find_config_file(args.config)
        config = load_config(config_path)
    except ConfigError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        return 1

    output = generate_crontab(config, config_path=config_path)
    print(output, end="")

    # Check staleness
    warning = check_crontab_staleness(config_path)
    if warning:
        print(f"\n⚠️  {warning}", file=sys.stderr)

    return 0


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

        # Set up logging (try to load config for log settings)
        try:
            config_path = find_config_file(getattr(args, 'config', None))
            config_for_logging = load_config(config_path)
        except (ConfigError, Exception):
            config_for_logging = None

        setup_logging(config=config_for_logging)
        logger = get_logger("cli")
        logger.info("x-digest %s — command: %s", __version__, args.command)

        if args.command == "run":
            exit_code = cmd_run(args)
        elif args.command == "validate":
            exit_code = cmd_validate(args)
        elif args.command == "crontab":
            exit_code = cmd_crontab(args)
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

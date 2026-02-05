"""
Command line interface for x-digest.

Provides CLI commands for running digests, validation, onboarding, and monitoring.
Supports multiple subcommands:

- run: Execute digest for a specific list
- watch: Run digests on an interval
- validate: Validate configuration file
- crontab: Generate crontab entries from config
- onboard: LLM-assisted list setup

The CLI handles argument parsing, config file discovery, and orchestrates
the entire digest pipeline from tweet fetching to delivery.
"""

import argparse
import sys
import os
import json
import time
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Optional

from . import __version__
from .config import load_config
from .errors import ConfigError, ErrorCode


def parse_duration(duration_str: str) -> int:
    """Parse duration string like '12h', '30m', '1h30m' to seconds."""
    from .watch import parse_interval
    return parse_interval(duration_str)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="x-digest",
        description="Twitter List Digest Pipeline"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"x-digest {__version__}"
    )
    
    # Global options
    parser.add_argument(
        "--config",
        help="Path to configuration file"
    )
    
    # Subcommands will be added in future milestones
    parser.add_argument(
        "command",
        nargs="?", 
        default="help",
        help="Command to run (placeholder)"
    )
    
    return parser.parse_args(argv)


def find_config_file() -> str:
    """Find config file in search order."""
    search_paths = [
        "./x-digest-config.json",
        os.path.expanduser("~/.config/x-digest/config.json")
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            return path
    
    raise ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)


def main():
    """Main CLI entry point."""
    try:
        args = parse_args()
        # Implementation will be added in milestones
        print(f"x-digest v{__version__} - CLI placeholder")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
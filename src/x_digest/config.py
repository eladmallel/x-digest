"""
Configuration loading and validation for x-digest.

Handles loading, parsing, and validating the x-digest configuration file.
Supports version checking, required field validation, and defaults merging.

The configuration uses a versioned schema to ensure compatibility and
enable future migrations. All configuration errors use predefined error codes
to maintain security (no dynamic content exposed to monitoring).
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path

from .errors import ConfigError, ErrorCode

# Expected configuration version
EXPECTED_CONFIG_VERSION = 1

# Default configuration values
DEFAULT_CONFIG = {
    "defaults": {
        "llm": {
            "provider": "gemini",
            "model": "gemini-2.0-flash"
        },
        "timezone": "America/New_York",
        "token_limits": {
            "max_input_tokens": 100000,
            "max_output_tokens": 4000,
            "warn_at_percent": 80
        },
        "pre_summarization": {
            "enabled": True,
            "long_tweet_chars": 500,
            "long_quote_chars": 300,
            "long_combined_chars": 600,
            "thread_min_tweets": 2,
            "max_summary_tokens": 300
        }
    },
    "retry": {
        "max_attempts": 3,
        "initial_delay_seconds": 2,
        "backoff_multiplier": 2,
        "max_delay_seconds": 30
    },
    "idempotency_window_minutes": 30
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load and validate configuration file.
    
    Args:
        config_path: Optional path to config file. If None, searches default locations.
        
    Returns:
        Validated configuration dictionary with defaults merged.
        
    Raises:
        ConfigError: If config file not found, invalid, or fails validation.
    """
    if config_path is None:
        config_path = _find_config_file()
    
    # Load raw config
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = json.load(f)
    except FileNotFoundError:
        raise ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)
    except json.JSONDecodeError:
        raise ConfigError(ErrorCode.CONFIG_INVALID_JSON)
    except PermissionError:
        raise ConfigError(ErrorCode.WRITE_PERMISSION_DENIED)
    
    # Validate version
    config_version = raw_config.get("version")
    if config_version != EXPECTED_CONFIG_VERSION:
        raise ConfigError(
            ErrorCode.CONFIG_VERSION_MISMATCH,
            f"Expected version {EXPECTED_CONFIG_VERSION}, got {config_version}"
        )
    
    # Validate required fields
    _validate_required_fields(raw_config)
    
    # Merge with defaults
    config = _merge_defaults(raw_config)
    
    # Additional validation
    _validate_config_values(config)
    
    return config


def _find_config_file() -> str:
    """Find configuration file in default search paths."""
    search_paths = [
        "./x-digest-config.json",
        os.path.expanduser("~/.config/x-digest/config.json")
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            return path
    
    raise ConfigError(ErrorCode.CONFIG_FILE_NOT_FOUND)


def _validate_required_fields(config: Dict[str, Any]) -> None:
    """Validate that all required fields are present."""
    required_fields = [
        "version",
        "lists"
    ]
    
    for field in required_fields:
        if field not in config:
            raise ConfigError(
                ErrorCode.CONFIG_MISSING_REQUIRED_FIELD,
                f"Required field '{field}' missing"
            )
    
    # Validate lists structure
    if not isinstance(config["lists"], dict):
        raise ConfigError(
            ErrorCode.CONFIG_INVALID_VALUE,
            "Field 'lists' must be an object"
        )
    
    for list_name, list_config in config["lists"].items():
        if not isinstance(list_config, dict):
            raise ConfigError(
                ErrorCode.CONFIG_INVALID_VALUE,
                f"List '{list_name}' must be an object"
            )
        
        if "id" not in list_config:
            raise ConfigError(
                ErrorCode.CONFIG_MISSING_REQUIRED_FIELD,
                f"List '{list_name}' missing required field 'id'"
            )


def _validate_config_values(config: Dict[str, Any]) -> None:
    """Validate configuration field values."""
    # Validate token limits
    token_limits = config["defaults"]["token_limits"]
    max_in = token_limits["max_input_tokens"]
    max_out = token_limits["max_output_tokens"]
    
    if max_in <= 0 or max_out <= 0:
        raise ConfigError(
            ErrorCode.CONFIG_INVALID_VALUE,
            "Token limits must be positive integers"
        )
    
    if max_in > 1000000:  # Gemini's actual limit
        raise ConfigError(
            ErrorCode.CONFIG_INVALID_VALUE,
            "max_input_tokens cannot exceed 1,000,000"
        )
    
    # Validate pre-summarization settings
    presummary = config["defaults"]["pre_summarization"]
    for field in ["long_tweet_chars", "long_quote_chars", "long_combined_chars", "thread_min_tweets"]:
        if presummary[field] <= 0:
            raise ConfigError(
                ErrorCode.CONFIG_INVALID_VALUE,
                f"pre_summarization.{field} must be positive"
            )
    
    # Validate retry settings
    retry = config["retry"]
    if retry["max_attempts"] <= 0:
        raise ConfigError(
            ErrorCode.CONFIG_INVALID_VALUE,
            "retry.max_attempts must be positive"
        )


def _merge_defaults(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user config with defaults."""
    config = DEFAULT_CONFIG.copy()
    
    # Deep merge for nested dictionaries
    for key, value in raw_config.items():
        if key in config and isinstance(config[key], dict) and isinstance(value, dict):
            config[key] = _deep_merge(config[key], value)
        else:
            config[key] = value
    
    return config


def _deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge two dictionaries."""
    result = base.copy()
    
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def get_list_config(config: Dict[str, Any], list_name: str) -> Dict[str, Any]:
    """Get configuration for a specific list with defaults applied."""
    if list_name not in config["lists"]:
        raise ConfigError(
            ErrorCode.CONFIG_INVALID_VALUE,
            f"List '{list_name}' not found in configuration"
        )
    
    list_config = config["lists"][list_name].copy()
    defaults = config["defaults"]
    
    # Apply defaults for optional list fields
    list_config.setdefault("display_name", list_name.title())
    list_config.setdefault("emoji", "📋")
    list_config.setdefault("enabled", True)
    list_config.setdefault("timezone", defaults["timezone"])
    
    return list_config
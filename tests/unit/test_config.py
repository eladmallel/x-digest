"""Tests for configuration loading and validation."""

import json
import pytest
from pathlib import Path
from x_digest.config import load_config, get_list_config, DEFAULT_CONFIG
from x_digest.errors import ConfigError, ErrorCode


def test_load_valid_config(tmp_path):
    """Valid config loads successfully."""
    config_file = tmp_path / "config.json"
    config_data = {
        "version": 1,
        "lists": {
            "test-list": {
                "id": "123456789"
            }
        }
    }
    config_file.write_text(json.dumps(config_data))
    
    cfg = load_config(str(config_file))
    assert cfg["version"] == 1
    assert "test-list" in cfg["lists"]
    assert cfg["lists"]["test-list"]["id"] == "123456789"


def test_wrong_version_raises(tmp_path):
    """Config with wrong version raises ConfigError."""
    config_file = tmp_path / "config.json"
    config_data = {"version": 99, "lists": {}}
    config_file.write_text(json.dumps(config_data))
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_VERSION_MISMATCH


def test_missing_lists_raises(tmp_path):
    """Config missing required field raises ConfigError."""
    config_file = tmp_path / "config.json"
    config_data = {"version": 1}  # Missing lists
    config_file.write_text(json.dumps(config_data))
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_MISSING_REQUIRED_FIELD


def test_invalid_json_raises(tmp_path):
    """Malformed JSON raises ConfigError."""
    config_file = tmp_path / "config.json"
    config_file.write_text('not json')
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_INVALID_JSON


def test_missing_file_raises():
    """Missing config file raises ConfigError."""
    with pytest.raises(ConfigError) as exc:
        load_config("/nonexistent/path/config.json")
    assert exc.value.code == ErrorCode.CONFIG_FILE_NOT_FOUND


def test_defaults_merge(tmp_path):
    """Config merges with defaults correctly."""
    config_file = tmp_path / "config.json"
    config_data = {
        "version": 1,
        "lists": {
            "test-list": {"id": "123"}
        }
    }
    config_file.write_text(json.dumps(config_data))
    
    cfg = load_config(str(config_file))
    
    # Should have defaults merged
    assert "defaults" in cfg
    assert "llm" in cfg["defaults"]
    assert cfg["defaults"]["llm"]["provider"] == "gemini"
    assert "token_limits" in cfg["defaults"]


def test_list_config_validation(tmp_path):
    """List entries must have required fields."""
    config_file = tmp_path / "config.json"
    config_data = {
        "version": 1,
        "lists": {
            "bad-list": {}  # Missing id field
        }
    }
    config_file.write_text(json.dumps(config_data))
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_MISSING_REQUIRED_FIELD


def test_get_list_config():
    """get_list_config returns list config with defaults."""
    config = {
        "defaults": {"timezone": "UTC"},
        "lists": {
            "test-list": {"id": "123"},
            "custom-list": {"id": "456", "display_name": "Custom", "emoji": "🎯"}
        }
    }
    
    # List with defaults applied
    list_cfg = get_list_config(config, "test-list")
    assert list_cfg["id"] == "123"
    assert list_cfg["display_name"] == "Test-List"  # Auto-generated
    assert list_cfg["emoji"] == "📋"  # Default emoji
    assert list_cfg["timezone"] == "UTC"  # From defaults
    assert list_cfg["enabled"] is True  # Default enabled
    
    # List with custom values
    custom_cfg = get_list_config(config, "custom-list")
    assert custom_cfg["display_name"] == "Custom"  # Custom value
    assert custom_cfg["emoji"] == "🎯"  # Custom emoji


def test_get_list_config_missing_list():
    """get_list_config raises for unknown list."""
    config = {"lists": {}, "defaults": {}}
    
    with pytest.raises(ConfigError) as exc:
        get_list_config(config, "unknown-list")
    assert exc.value.code == ErrorCode.CONFIG_INVALID_VALUE


def test_token_limits_validation(tmp_path):
    """Token limits must be positive."""
    config_file = tmp_path / "config.json"
    config_data = {
        "version": 1,
        "lists": {"test": {"id": "123"}},
        "defaults": {
            "token_limits": {
                "max_input_tokens": -100  # Invalid negative value
            }
        }
    }
    config_file.write_text(json.dumps(config_data))
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_INVALID_VALUE


# Additional config edge case tests

def test_very_large_token_limits(tmp_path):
    """Very large token limits are rejected."""
    config_file = tmp_path / "config.json"
    config = {
        "version": 1,
        "lists": {"test": {"id": "123"}},
        "defaults": {
            "token_limits": {"max_input_tokens": 2000000}  # Over 1M limit
        }
    }
    config_file.write_text(json.dumps(config))
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_INVALID_VALUE


def test_invalid_presummary_thresholds(tmp_path):
    """Invalid pre-summarization thresholds are rejected."""
    config_file = tmp_path / "config.json"
    config = {
        "version": 1,
        "lists": {"test": {"id": "123"}},
        "defaults": {
            "pre_summarization": {"long_tweet_chars": 0}  # Invalid
        }
    }
    config_file.write_text(json.dumps(config))
    
    with pytest.raises(ConfigError) as exc:
        load_config(str(config_file))
    assert exc.value.code == ErrorCode.CONFIG_INVALID_VALUE


def test_deep_merge_preserves_defaults(tmp_path):
    """Deep merge works correctly with partial overrides."""
    config_file = tmp_path / "config.json"
    config = {
        "version": 1,
        "lists": {"test": {"id": "123"}},
        "defaults": {
            "token_limits": {
                "max_output_tokens": 2000  # Override default 4000
                # max_input_tokens should stay at default 100000
            }
        }
    }
    config_file.write_text(json.dumps(config))
    
    result = load_config(str(config_file))
    
    # Check merge worked correctly
    limits = result["defaults"]["token_limits"]
    assert limits["max_output_tokens"] == 2000  # Overridden
    assert limits["max_input_tokens"] == 100000  # Default preserved
    assert limits["warn_at_percent"] == 80  # Default preserved


def test_config_file_search_order():
    """Config search follows documented order."""
    from x_digest.config import _find_config_file
    
    # Should raise ConfigError when no files exist
    with pytest.raises(ConfigError) as exc:
        _find_config_file()
    assert exc.value.code == ErrorCode.CONFIG_FILE_NOT_FOUND


def test_empty_lists_config(tmp_path):
    """Empty lists configuration is valid."""
    config_file = tmp_path / "config.json"
    config = {
        "version": 1,
        "lists": {}  # Empty but valid
    }
    config_file.write_text(json.dumps(config))
    
    # Should load without error
    result = load_config(str(config_file))
    assert result["lists"] == {}


def test_list_config_defaults():
    """get_list_config applies correct defaults."""
    config = {
        "lists": {
            "minimal": {"id": "123"},
            "custom": {
                "id": "456",
                "display_name": "Custom List",
                "emoji": "🔥"
            }
        },
        "defaults": {"timezone": "UTC"}
    }
    
    # Minimal list gets defaults
    minimal = get_list_config(config, "minimal")
    assert minimal["display_name"] == "Minimal"  # Title-cased
    assert minimal["emoji"] == "📋"  # Default
    assert minimal["enabled"] is True  # Default
    assert minimal["timezone"] == "UTC"  # From config
    
    # Custom list preserves overrides
    custom = get_list_config(config, "custom")
    assert custom["display_name"] == "Custom List"
    assert custom["emoji"] == "🔥"
"""Shared fixtures for integration tests."""

import json
import os
from pathlib import Path
from typing import List

import pytest

from x_digest.models import Tweet, parse_tweets


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "tweets"


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return FIXTURES_DIR


def load_fixture(name: str) -> List[Tweet]:
    """Load a tweet fixture file and parse into Tweet objects."""
    fixture_path = FIXTURES_DIR / name
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_tweets(data)


def load_fixture_raw(name: str) -> list:
    """Load a tweet fixture file as raw JSON."""
    fixture_path = FIXTURES_DIR / name
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)

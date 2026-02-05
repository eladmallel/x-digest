"""Tests for pipeline artifact saving."""

import json
import os
from datetime import datetime, UTC
from pathlib import Path
import pytest

from x_digest.artifacts import save_artifacts, _build_artifact_dir, _tweets_to_json
from x_digest.models import Tweet, Author, Media


def _make_tweet(
    id: str = "123",
    text: str = "Test tweet",
    username: str = "testuser",
    name: str = "Test User",
    like_count: int = 10,
    media: list = None,
    quoted_tweet: "Tweet" = None,
    in_reply_to: str = None,
) -> Tweet:
    """Helper to create test Tweet objects."""
    return Tweet(
        id=id,
        text=text,
        created_at="Wed Feb 04 19:00:43 +0000 2026",
        conversation_id=id,
        author=Author(username=username, name=name),
        author_id="1",
        reply_count=0,
        retweet_count=0,
        like_count=like_count,
        media=media,
        quoted_tweet=quoted_tweet,
        in_reply_to_status_id=in_reply_to,
    )


class TestBuildArtifactDir:
    """Tests for artifact directory path building."""

    def test_basic_path(self):
        """Builds correct directory path from timestamp."""
        ts = datetime(2026, 2, 4, 12, 0, 0, tzinfo=UTC)
        path = _build_artifact_dir("/data", "ai-dev", ts)
        # 2026-02-04 is in ISO week 6
        assert path == Path("/data/digests/2026/02/week-06/2026-02-04/ai-dev")

    def test_path_with_different_date(self):
        """Path changes with different dates."""
        ts1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 12, 31, 12, 0, 0, tzinfo=UTC)
        path1 = _build_artifact_dir("/data", "test", ts1)
        path2 = _build_artifact_dir("/data", "test", ts2)
        assert "2026/01" in str(path1)
        assert "2026/12" in str(path2)
        assert path1 != path2

    def test_uses_current_time_by_default(self):
        """Uses current time when no timestamp given."""
        path = _build_artifact_dir("/data", "test")
        now = datetime.now(UTC)
        assert now.strftime("%Y") in str(path)


class TestTweetsToJson:
    """Tests for Tweet to JSON serialization."""

    def test_basic_tweet(self):
        """Basic tweet serializes correctly."""
        tweet = _make_tweet(id="456", text="Hello world")
        result = _tweets_to_json([tweet])
        assert len(result) == 1
        assert result[0]["id"] == "456"
        assert result[0]["text"] == "Hello world"
        assert result[0]["author"]["username"] == "testuser"

    def test_tweet_with_media(self):
        """Tweet with media serializes correctly."""
        media = [Media(
            type="photo", url="http://img.jpg", width=100, height=100,
            preview_url="http://thumb.jpg"
        )]
        tweet = _make_tweet(media=media)
        result = _tweets_to_json([tweet])
        assert len(result[0]["media"]) == 1
        assert result[0]["media"][0]["type"] == "photo"
        assert result[0]["media"][0]["url"] == "http://img.jpg"

    def test_tweet_with_quote(self):
        """Tweet with quoted tweet serializes recursively."""
        quoted = _make_tweet(id="original", text="Original text")
        tweet = _make_tweet(id="quote", text="Quoting this", quoted_tweet=quoted)
        result = _tweets_to_json([tweet])
        assert "quotedTweet" in result[0]
        assert result[0]["quotedTweet"]["id"] == "original"

    def test_tweet_with_reply(self):
        """Reply tweet includes inReplyToStatusId."""
        tweet = _make_tweet(in_reply_to="parent123")
        result = _tweets_to_json([tweet])
        assert result[0]["inReplyToStatusId"] == "parent123"


class TestSaveArtifacts:
    """Tests for full artifact saving."""

    def test_creates_all_files(self, tmp_path):
        """All artifact files are created."""
        tweets = [_make_tweet(id="1", text="Tweet one")]
        summaries = {"1": "Summary of tweet one"}

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="ai-dev",
            tweets=tweets,
            summaries=summaries,
            payload_text="# Payload\nTest payload",
            system_prompt="You are a curator",
            digest_text="## Top\n- Item one",
        )

        assert (artifact_dir / "raw-tweets.json").exists()
        assert (artifact_dir / "pre-summaries.json").exists()
        assert (artifact_dir / "prompt.md").exists()
        assert (artifact_dir / "digest.md").exists()
        assert (artifact_dir / "meta.json").exists()

    def test_raw_tweets_content(self, tmp_path):
        """raw-tweets.json contains tweet data."""
        tweets = [
            _make_tweet(id="1", text="First tweet"),
            _make_tweet(id="2", text="Second tweet"),
        ]

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries={},
            payload_text="",
            system_prompt="",
            digest_text="",
        )

        raw = json.loads((artifact_dir / "raw-tweets.json").read_text())
        assert len(raw) == 2
        assert raw[0]["id"] == "1"
        assert raw[1]["id"] == "2"

    def test_pre_summaries_content(self, tmp_path):
        """pre-summaries.json contains summary data."""
        tweets = [_make_tweet()]
        summaries = {"123": "Summary text here"}

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries=summaries,
            payload_text="",
            system_prompt="",
            digest_text="",
        )

        presums = json.loads((artifact_dir / "pre-summaries.json").read_text())
        assert len(presums) == 1
        assert presums[0]["tweet_id"] == "123"
        assert presums[0]["summary"] == "Summary text here"

    def test_prompt_contains_system_and_payload(self, tmp_path):
        """prompt.md contains both system prompt and payload."""
        tweets = [_make_tweet()]

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries={},
            payload_text="Payload text here",
            system_prompt="System prompt here",
            digest_text="",
        )

        prompt = (artifact_dir / "prompt.md").read_text()
        assert "System prompt here" in prompt
        assert "Payload text here" in prompt

    def test_digest_content(self, tmp_path):
        """digest.md contains the generated digest."""
        tweets = [_make_tweet()]
        digest_text = "## 🔥 Top\n\n- Great content"

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries={},
            payload_text="",
            system_prompt="",
            digest_text=digest_text,
        )

        assert (artifact_dir / "digest.md").read_text() == digest_text

    def test_meta_json_structure(self, tmp_path):
        """meta.json has required fields."""
        tweets = [_make_tweet()]

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="ai-dev",
            tweets=tweets,
            summaries={"123": "summary"},
            payload_text="",
            system_prompt="",
            digest_text="",
            fetch_ms=1000,
            presummary_ms=2000,
            digest_ms=3000,
            delivery_ms=500,
            pre_summarized_count=1,
            image_count=3,
            success=True,
        )

        meta = json.loads((artifact_dir / "meta.json").read_text())
        assert meta["list"] == "ai-dev"
        assert meta["success"] is True
        assert meta["tweets"]["fetched"] == 1
        assert meta["tweets"]["pre_summarized"] == 1
        assert meta["images"]["included"] == 3
        assert meta["timing"]["fetch_ms"] == 1000
        assert meta["timing"]["pre_summary_ms"] == 2000
        assert meta["timing"]["digest_ms"] == 3000
        assert meta["timing"]["delivery_ms"] == 500
        assert meta["timing"]["total_ms"] == 6500
        assert "timestamp" in meta

    def test_directory_structure(self, tmp_path):
        """Artifact directory follows year/month/week/date/list pattern."""
        ts = datetime(2026, 2, 4, 12, 0, 0, tzinfo=UTC)
        tweets = [_make_tweet()]

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="investing",
            tweets=tweets,
            summaries={},
            payload_text="",
            system_prompt="",
            digest_text="",
            timestamp=ts,
        )

        # Check path components
        rel = artifact_dir.relative_to(tmp_path)
        parts = rel.parts
        assert parts[0] == "digests"
        assert parts[1] == "2026"
        assert parts[2] == "02"
        assert parts[3].startswith("week-")
        assert parts[4] == "2026-02-04"
        assert parts[5] == "investing"

    def test_returns_artifact_directory(self, tmp_path):
        """save_artifacts returns the Path to the artifact directory."""
        tweets = [_make_tweet()]
        result = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries={},
            payload_text="",
            system_prompt="",
            digest_text="",
        )
        assert isinstance(result, Path)
        assert result.exists()
        assert result.is_dir()

    def test_unicode_content(self, tmp_path):
        """Artifact saving handles Unicode (Hebrew, emoji) correctly."""
        tweets = [_make_tweet(text="שלום עולם 🇮🇱")]

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries={},
            payload_text="",
            system_prompt="",
            digest_text="🔥 *Top* — Hebrew content",
        )

        raw = json.loads((artifact_dir / "raw-tweets.json").read_text())
        assert "שלום" in raw[0]["text"]
        digest = (artifact_dir / "digest.md").read_text()
        assert "🔥" in digest

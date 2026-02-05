"""Integration test: Full pipeline run with mock delivery."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from x_digest.models import parse_tweets
from x_digest.classify import categorize_tweets, dedupe_quotes, reconstruct_threads
from x_digest.presummary import presummary_tweets, should_presummary
from x_digest.images import prioritize_images, get_image_stats
from x_digest.digest import (
    generate_digest,
    split_digest,
    build_digest_payload,
    build_system_prompt,
    format_empty_digest,
    format_sparse_digest,
)
from x_digest.delivery.base import MockDeliveryProvider, send_digest
from x_digest.llm.base import MockLLMProvider
from x_digest.artifacts import save_artifacts

from .conftest import load_fixture, load_fixture_raw


class TestFullPipelineWithMockLLM:
    """Full pipeline run with mock LLM and mock delivery."""

    def test_full_pipeline_50_tweets(self):
        """Full pipeline processes 50-tweet fixture end to end."""
        # Step 1: Load and parse
        tweets = load_fixture("mixed_batch_50.json")
        assert len(tweets) == 50

        # Step 2: Classify
        deduped = dedupe_quotes(tweets)
        assert len(deduped) < len(tweets)

        categories = categorize_tweets(deduped)
        threads = reconstruct_threads(deduped)

        # Step 3: Pre-summarize with mock LLM
        mock_llm = MockLLMProvider(response="This is a concise summary of the content.")
        summaries_list = presummary_tweets(deduped, mock_llm)

        summaries = {}
        for tweet, summary in summaries_list:
            if summary is not None:
                summaries[tweet.id] = summary

        # Should have some pre-summarized items (threads, long tweets in the 50-tweet batch)
        # The 10-tweet thread should trigger presummary
        assert len(mock_llm.calls) > 0

        # Step 4: Image prioritization
        selected_images = prioritize_images(deduped)
        # Should have some images from the media tweets
        image_stats = get_image_stats(deduped)
        assert image_stats["total_images"] > 0

        # Step 5: Build digest payload
        config = {
            "display_name": "AI & Dev",
            "emoji": "🤖",
            "list_name": "ai-dev",
            "defaults": {},
        }
        payload = build_digest_payload(deduped, summaries, selected_images, config)
        assert "AI & Dev" in payload
        assert "Tweet 1" in payload
        assert "@" in payload  # Should have author references

        # Step 6: Generate digest with mock LLM
        mock_llm.set_response("## 🔥 Top\n\n- Great tweet about AI\n\n## 💡 Worth Noting\n\n- Another thing")
        digest = generate_digest(deduped, summaries, selected_images, config, mock_llm)
        assert len(digest) > 0
        assert "🔥" in digest

        # Step 7: Split and deliver
        parts = split_digest(digest)
        assert len(parts) >= 1
        for part in parts:
            assert len(part) <= 4000

        # Step 8: Mock delivery
        mock_delivery = MockDeliveryProvider(success=True)
        success = send_digest(parts, mock_delivery, "+1234567890")
        assert success is True
        assert len(mock_delivery.sends) == len(parts)

    def test_pipeline_with_empty_tweets(self):
        """Pipeline handles empty fixture correctly."""
        tweets = load_fixture("empty.json")
        assert len(tweets) == 0

        config = {
            "display_name": "Test",
            "emoji": "📋",
            "list_name": "test",
        }
        digest = format_empty_digest("test", config)
        assert "Quiet period" in digest or "No new tweets" in digest

    def test_pipeline_with_sparse_tweets(self):
        """Pipeline handles sparse fixture (< 5 tweets) without LLM."""
        tweets = load_fixture("single_tweet.json")
        assert len(tweets) < 5

        config = {
            "display_name": "Test",
            "emoji": "📋",
            "list_name": "test",
        }
        digest = format_sparse_digest(tweets, config)
        assert "@devlead" in digest
        assert "❤️" in digest

    def test_pipeline_produces_correct_output_at_each_stage(self):
        """Verify output structure at each pipeline stage."""
        tweets = load_fixture("mixed_batch_50.json")

        # Classification output
        deduped = dedupe_quotes(tweets)
        categories = categorize_tweets(deduped)
        assert isinstance(categories, dict)
        assert set(categories.keys()) == {"standalone", "threads", "quotes", "replies", "retweets"}

        # Thread reconstruction
        threads = reconstruct_threads(deduped)
        assert isinstance(threads, dict)
        for conv_id, thread in threads.items():
            assert isinstance(conv_id, str)
            assert isinstance(thread, list)
            assert all(hasattr(t, "id") for t in thread)

        # Pre-summarization
        mock_llm = MockLLMProvider(response="Summary")
        results = presummary_tweets(deduped, mock_llm)
        assert isinstance(results, list)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

        # Image selection
        images = prioritize_images(deduped)
        assert isinstance(images, list)
        assert all(isinstance(img, tuple) and len(img) == 2 for img in images)

    def test_performance_baseline(self):
        """Full pipeline on 50-tweet fixture completes in < 30s."""
        start = time.time()

        tweets = load_fixture("mixed_batch_50.json")
        deduped = dedupe_quotes(tweets)
        categories = categorize_tweets(deduped)
        threads = reconstruct_threads(deduped)

        mock_llm = MockLLMProvider(response="Summary of content")
        summaries_list = presummary_tweets(deduped, mock_llm)
        summaries = {t.id: s for t, s in summaries_list if s}

        images = prioritize_images(deduped)

        config = {"display_name": "Test", "emoji": "📋", "list_name": "test", "defaults": {}}
        mock_llm.set_response("## 🔥 Top\n- Content here")
        digest = generate_digest(deduped, summaries, images, config, mock_llm)
        parts = split_digest(digest)

        elapsed = time.time() - start
        assert elapsed < 30, f"Pipeline took {elapsed:.1f}s (max 30s)"


class TestArtifactSavingIntegration:
    """Integration tests for artifact saving with real pipeline data."""

    def test_artifacts_created_from_pipeline(self, tmp_path):
        """Full pipeline artifacts are saved correctly."""
        tweets = load_fixture("mixed_batch_50.json")
        deduped = dedupe_quotes(tweets)

        mock_llm = MockLLMProvider(response="Summary")
        summaries_list = presummary_tweets(deduped, mock_llm)
        summaries = {t.id: s for t, s in summaries_list if s}

        images = prioritize_images(deduped)
        config = {"display_name": "AI & Dev", "emoji": "🤖", "list_name": "ai-dev", "defaults": {}}

        payload = build_digest_payload(deduped, summaries, images, config)
        system_prompt = build_system_prompt(config)

        mock_llm.set_response("## 🔥 Top\n- AI stuff")
        digest = generate_digest(deduped, summaries, images, config, mock_llm)

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="ai-dev",
            tweets=tweets,
            summaries=summaries,
            payload_text=payload,
            system_prompt=system_prompt,
            digest_text=digest,
            fetch_ms=100,
            presummary_ms=200,
            digest_ms=300,
            pre_summarized_count=len(summaries),
            image_count=len(images),
        )

        # Verify all files
        assert (artifact_dir / "raw-tweets.json").exists()
        assert (artifact_dir / "pre-summaries.json").exists()
        assert (artifact_dir / "prompt.md").exists()
        assert (artifact_dir / "digest.md").exists()
        assert (artifact_dir / "meta.json").exists()

        # Verify raw tweets
        raw = json.loads((artifact_dir / "raw-tweets.json").read_text())
        assert len(raw) == 50

        # Verify meta
        meta = json.loads((artifact_dir / "meta.json").read_text())
        assert meta["list"] == "ai-dev"
        assert meta["tweets"]["fetched"] == 50
        assert meta["timing"]["fetch_ms"] == 100

    def test_artifacts_with_thread_fixture(self, tmp_path):
        """Artifacts save correctly for thread fixture."""
        tweets = load_fixture("thread_5_tweets.json")

        artifact_dir = save_artifacts(
            data_dir=str(tmp_path),
            list_name="test",
            tweets=tweets,
            summaries={"2019123973615939775": "Thread summary"},
            payload_text="Thread payload",
            system_prompt="System",
            digest_text="Thread digest",
        )

        raw = json.loads((artifact_dir / "raw-tweets.json").read_text())
        assert len(raw) == 5
        # Verify thread structure preserved
        assert all(r["conversationId"] == raw[0]["conversationId"] for r in raw)

"""
Artifact saving for x-digest pipeline runs.

Saves pipeline outputs (raw tweets, pre-summaries, prompts, digests, metadata)
to an organized directory structure for historical analysis and debugging.

Directory structure:
    data/digests/{year}/{month}/{week}/{date}/{list}/
        raw-tweets.json
        pre-summaries.json
        prompt.md
        digest.md
        meta.json
"""

import json
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, List, Any, Optional

from .models import Tweet
from .logging import get_logger


def _build_artifact_dir(data_dir: str, list_name: str, timestamp: Optional[datetime] = None) -> Path:
    """
    Build the artifact directory path for a run.

    Args:
        data_dir: Base data directory
        list_name: Name of the list
        timestamp: Run timestamp (defaults to now)

    Returns:
        Path to the artifact directory
    """
    if timestamp is None:
        timestamp = datetime.now(UTC)

    year = timestamp.strftime("%Y")
    month = timestamp.strftime("%m")
    week = f"week-{timestamp.isocalendar()[1]:02d}"
    day = timestamp.strftime("%Y-%m-%d")

    return Path(data_dir) / "digests" / year / month / week / day / list_name


def _tweets_to_json(tweets: List[Tweet]) -> List[Dict[str, Any]]:
    """Convert Tweet objects back to JSON-serializable dicts."""
    result = []
    for tweet in tweets:
        d: Dict[str, Any] = {
            "id": tweet.id,
            "text": tweet.text,
            "createdAt": tweet.created_at,
            "conversationId": tweet.conversation_id,
            "author": {
                "username": tweet.author.username,
                "name": tweet.author.name,
            },
            "authorId": tweet.author_id,
            "replyCount": tweet.reply_count,
            "retweetCount": tweet.retweet_count,
            "likeCount": tweet.like_count,
        }

        if tweet.in_reply_to_status_id:
            d["inReplyToStatusId"] = tweet.in_reply_to_status_id

        if tweet.media:
            d["media"] = [
                {
                    "type": m.type,
                    "url": m.url,
                    "width": m.width,
                    "height": m.height,
                    "previewUrl": m.preview_url,
                    **({"videoUrl": m.video_url} if m.video_url else {}),
                    **({"durationMs": m.duration_ms} if m.duration_ms else {}),
                }
                for m in tweet.media
            ]

        if tweet.quoted_tweet:
            d["quotedTweet"] = _tweets_to_json([tweet.quoted_tweet])[0]

        result.append(d)
    return result


def save_artifacts(
    data_dir: str,
    list_name: str,
    tweets: List[Tweet],
    summaries: Dict[str, str],
    payload_text: str,
    system_prompt: str,
    digest_text: str,
    fetch_ms: int = 0,
    presummary_ms: int = 0,
    digest_ms: int = 0,
    delivery_ms: int = 0,
    pre_summarized_count: int = 0,
    image_count: int = 0,
    success: bool = True,
    timestamp: Optional[datetime] = None,
) -> Path:
    """
    Save all pipeline artifacts for a run.

    Args:
        data_dir: Base data directory
        list_name: Name of the list
        tweets: List of fetched Tweet objects
        summaries: Dict of tweet_id -> summary text
        payload_text: The formatted payload sent to the LLM
        system_prompt: The system prompt used
        digest_text: The generated digest
        fetch_ms: Time spent fetching (ms)
        presummary_ms: Time spent pre-summarizing (ms)
        digest_ms: Time spent generating digest (ms)
        delivery_ms: Time spent delivering (ms)
        pre_summarized_count: Number of pre-summarized items
        image_count: Number of images included
        success: Whether the run was successful
        timestamp: Run timestamp (defaults to now)

    Returns:
        Path to the artifact directory
    """
    logger = get_logger("artifacts")

    if timestamp is None:
        timestamp = datetime.now(UTC)

    artifact_dir = _build_artifact_dir(data_dir, list_name, timestamp)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 1. raw-tweets.json
    raw_path = artifact_dir / "raw-tweets.json"
    raw_path.write_text(
        json.dumps(_tweets_to_json(tweets), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug("Saved raw-tweets.json (%d tweets)", len(tweets))

    # 2. pre-summaries.json
    presummary_path = artifact_dir / "pre-summaries.json"
    presummary_data = [
        {"tweet_id": tid, "summary": summary}
        for tid, summary in summaries.items()
    ]
    presummary_path.write_text(
        json.dumps(presummary_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug("Saved pre-summaries.json (%d summaries)", len(summaries))

    # 3. prompt.md (system prompt + payload)
    prompt_path = artifact_dir / "prompt.md"
    prompt_content = f"# System Prompt\n\n{system_prompt}\n\n---\n\n# Payload\n\n{payload_text}"
    prompt_path.write_text(prompt_content, encoding="utf-8")
    logger.debug("Saved prompt.md")

    # 4. digest.md
    digest_path = artifact_dir / "digest.md"
    digest_path.write_text(digest_text, encoding="utf-8")
    logger.debug("Saved digest.md")

    # 5. meta.json
    total_ms = fetch_ms + presummary_ms + digest_ms + delivery_ms
    tweets_with_images = sum(1 for t in tweets if t.media)

    meta = {
        "timestamp": timestamp.isoformat(),
        "list": list_name,
        "success": success,
        "tweets": {
            "fetched": len(tweets),
            "pre_summarized": pre_summarized_count,
            "with_images": tweets_with_images,
        },
        "images": {
            "included": image_count,
        },
        "timing": {
            "fetch_ms": fetch_ms,
            "pre_summary_ms": presummary_ms,
            "digest_ms": digest_ms,
            "delivery_ms": delivery_ms,
            "total_ms": total_ms,
        },
    }

    meta_path = artifact_dir / "meta.json"
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.debug("Saved meta.json")

    logger.info("Artifacts saved to %s", artifact_dir)
    return artifact_dir

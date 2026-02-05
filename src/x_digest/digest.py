"""
Digest generation logic.

Handles the final LLM call to generate organized, formatted digests from
processed tweet data. Includes payload building, sparse feed handling,
and message splitting for delivery.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, UTC
from .models import Tweet
from .llm.base import LLMProvider
from .errors import LLMError, ErrorCode
from .utils import format_relative_time


# Minimum tweets required for LLM processing
MIN_TWEETS_FOR_LLM = 5
MAX_MESSAGE_LENGTH = 4000  # WhatsApp/Telegram safe limit


def generate_digest(
    tweets: List[Tweet],
    summaries: Dict[str, str],
    images: List[Tuple[str, str]],
    config: Dict[str, Any],
    llm_provider: LLMProvider
) -> str:
    """
    Generate digest from processed tweets.
    
    Args:
        tweets: List of Tweet objects
        summaries: Dictionary mapping tweet_id to pre-summary text
        images: List of (tweet_id, image_url) tuples for selected images
        config: Configuration dictionary
        llm_provider: LLM provider for digest generation
        
    Returns:
        Formatted digest text ready for delivery
        
    Logic:
    - If 0 tweets: return empty digest message
    - If < MIN_TWEETS_FOR_LLM: return sparse digest (no LLM)
    - Otherwise: build payload and call LLM for full digest
    """
    list_name = config.get("list_name", "Unknown List")
    
    if len(tweets) == 0:
        return format_empty_digest(list_name, config)
    
    if len(tweets) < MIN_TWEETS_FOR_LLM:
        return format_sparse_digest(tweets, config)
    
    # Full LLM digest generation
    payload = build_digest_payload(tweets, summaries, images, config)
    system_prompt = build_system_prompt(config)
    
    try:
        # Prepare images for multimodal LLM call
        image_data = []
        for tweet_id, image_url in images:
            try:
                from .images import fetch_and_encode
                encoded = fetch_and_encode(image_url)
                image_data.append(encoded)
            except Exception:
                # Skip failed images rather than failing whole digest
                continue
        
        digest = llm_provider.generate(payload, system=system_prompt, images=image_data)
        return digest.strip()
        
    except LLMError:
        # Fallback to sparse format if LLM fails
        return format_sparse_digest(tweets, config)


def build_digest_payload(
    tweets: List[Tweet],
    summaries: Dict[str, str],
    images: List[Tuple[str, str]],
    config: Dict[str, Any]
) -> str:
    """
    Build structured payload for digest LLM.
    
    Args:
        tweets: List of Tweet objects
        summaries: Pre-summaries mapping
        images: Selected images list
        config: Configuration
        
    Returns:
        Markdown-formatted payload string
    """
    list_name = config.get("display_name", "List")
    emoji = config.get("emoji", "📋")
    
    # Build header
    now = datetime.now(UTC)
    payload_lines = [
        f"# Digest Request: {emoji} {list_name}",
        f"**Period:** {now.strftime('%b %d, %Y')}",
        f"**Tweets:** {len(tweets)} total ({len(summaries)} pre-summarized, {len(images)} with images)",
        "",
        "---",
        ""
    ]
    
    # Build tweet entries
    image_map = {tweet_id: url for tweet_id, url in images}
    
    for i, tweet in enumerate(tweets, 1):
        payload_lines.append(f"## Tweet {i}")
        
        # Author and metadata
        payload_lines.append(f"- **Author:** @{tweet.author.username} ({tweet.author.name})")
        payload_lines.append(f"- **Time:** {_format_relative_time(tweet.created_at)}")
        payload_lines.append(f"- **Engagement:** {tweet.like_count} ❤️ · {tweet.retweet_count} 🔁 · {tweet.reply_count} 💬")
        
        # Content (pre-summarized or original)
        if tweet.id in summaries:
            payload_lines.append(f"- **Summary:** {summaries[tweet.id]}")
            payload_lines.append(f"- **Original:** {len(tweet.text)} chars")
        else:
            payload_lines.append(f"- **Text:** {tweet.text}")
        
        # Quote handling
        if tweet.quoted_tweet:
            quoted = tweet.quoted_tweet
            payload_lines.append(f"- **Quote:** @{quoted.author.username}: \"{quoted.text}\"")
        
        # Link to original
        payload_lines.append(f"- **Link:** https://x.com/{tweet.author.username}/status/{tweet.id}")
        
        # Image placeholder
        if tweet.id in image_map:
            payload_lines.append("- **[Image attached]**")
        
        payload_lines.append("")
        payload_lines.append("---")
        payload_lines.append("")
    
    return "\n".join(payload_lines)


def build_system_prompt(config: Dict[str, Any]) -> str:
    """
    Build system prompt for digest LLM.
    
    Uses hierarchy: list-specific -> default -> built-in
    """
    # Check for list-specific prompt
    if "prompt" in config:
        return config["prompt"]
    
    # Check for default prompt
    defaults = config.get("defaults", {})
    if "prompt" in defaults:
        return defaults["prompt"]
    
    # Built-in default prompt
    return _get_builtin_digest_prompt()


def format_empty_digest(list_name: str, config: Dict[str, Any]) -> str:
    """Format empty digest when no tweets found."""
    emoji = config.get("emoji", "📋")
    display_name = config.get("display_name", list_name)
    
    now = datetime.now(UTC)
    date_str = now.strftime("%b %d, %Y")
    
    return f"""{emoji} *{display_name} Digest* — {date_str}

📭 *Quiet period* — No new tweets since last digest."""


def format_sparse_digest(tweets: List[Tweet], config: Dict[str, Any]) -> str:
    """Format simple digest for small number of tweets (no LLM)."""
    emoji = config.get("emoji", "📋")
    display_name = config.get("display_name", config.get("list_name", "List"))
    
    now = datetime.now(UTC)
    date_str = now.strftime("%b %d, %Y")
    
    lines = [
        f"{emoji} *{display_name} Digest* — {date_str}",
        "",
        f"📋 *{len(tweets)} tweets since last digest:*",
        ""
    ]
    
    # Simple bullet list format
    for tweet in tweets:
        engagement = tweet.like_count
        lines.append(f"• @{tweet.author.username}: {tweet.text[:100]}{'...' if len(tweet.text) > 100 else ''}")
        lines.append(f"  {engagement} ❤️ · https://x.com/{tweet.author.username}/status/{tweet.id}")
        lines.append("")
    
    return "\n".join(lines)


def split_digest(digest: str, max_length: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Split long digest into multiple messages at section boundaries.
    
    Args:
        digest: Full digest text
        max_length: Maximum length per message
        
    Returns:
        List of message parts, with part indicators if split
        
    Split priority:
    1. Section headers (🔥, 💡, 🚀, etc.)
    2. Bold item starts (*text*)
    3. Paragraph breaks
    4. Hard split (emergency)
    """
    if len(digest) <= max_length:
        return [digest]
    
    # Split markers in priority order
    split_markers = [
        "\n\n🔥",    # Top section
        "\n\n💡",    # Worth Noting section  
        "\n\n🚀",    # Topical sections
        "\n\n🛠️",
        "\n\n📜",
        "\n\n💰",
        "\n\n🎯",
        "\n\n*",     # Any bold item start
        "\n\n",      # Paragraph break (fallback)
    ]
    
    parts = []
    remaining = digest
    
    while len(remaining) > max_length:
        split_at = None
        
        # Find best split point before the limit
        for marker in split_markers:
            idx = remaining.rfind(marker, 0, max_length)
            if idx > 0:
                split_at = idx
                break
        
        if split_at is None:
            # Emergency: hard split at limit (subtract part indicator length)
            split_at = max_length - 10  # Leave room for part indicator
        
        parts.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    
    if remaining:
        parts.append(remaining)
    
    # Add part indicators if multiple parts
    if len(parts) > 1:
        total = len(parts)
        parts = [f"{part}\n\n_({i+1}/{total})_" for i, part in enumerate(parts)]
    
    return parts


def _format_relative_time(created_at: str) -> str:
    """Format tweet timestamp as relative time."""
    return format_relative_time(created_at)


def _get_builtin_digest_prompt() -> str:
    """Get built-in digest system prompt."""
    return """You are a Twitter digest curator helping extract signal from noise.

YOUR GOAL: Surface the most valuable content so the reader doesn't have to scroll through the full feed. Prioritize by:
1. ENGAGEMENT — High likes/replies/retweets indicate resonance
2. PATTERNS — If multiple people are discussing the same topic, that's a signal
3. NOTABLE AUTHORS — Known experts or primary sources over commentators

INPUT: Tweets from a curated list, possibly with pre-summarized threads/long content.

OUTPUT STRUCTURE:
- Start with 🔥 *Top* (3-5 items) — the most important content
- Add topical sections if a theme dominates (e.g., "🚀 *Claude Cowork Launch*" if 5+ tweets discuss it)
- End with 💡 *Worth Noting* (2-4 items) — interesting but not top-tier
- Skip any section with no content; don't force structure

FORMATTING:
- *bold* for emphasis (WhatsApp-compatible)
- 1-2 sentences per item, max
- Format: Summary — @author https://x.com/{username}/status/{id}
- Group related content (quote + original, reactions to same news)
- For non-English content: translate to English, prefix with [Language] tag (e.g., [Hebrew], [Spanish])
- Skip pure retweets unless they add context

PATTERN RECOGNITION:
If you notice a theme (product launch, drama, breaking news), create a dedicated section for it. Example: if 6 tweets discuss "Mistral's new speech model", group them under "🎙️ *Mistral Voxtral Launch*" rather than scattering across sections."""
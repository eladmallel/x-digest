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
    
    Uses hierarchy: list-specific prompt -> default prompt -> built-in with sections from config.
    
    Sections are read directly from config as a list of dicts with keys:
    emoji, name, description. No hard-coded section registry needed.
    """
    # Check for list-specific prompt override
    if "prompt" in config:
        return config["prompt"]
    
    # Check for default prompt override
    defaults = config.get("defaults", {})
    if "prompt" in defaults:
        return defaults["prompt"]
    
    # Built-in prompt, customized with sections from config if available
    sections = config.get("sections")
    if sections and isinstance(sections, list) and len(sections) > 0:
        return _get_builtin_digest_prompt_with_sections(sections)
    
    return _get_builtin_digest_prompt()


def _get_builtin_digest_prompt_with_sections(sections: List[Dict[str, Any]]) -> str:
    """Build digest prompt entirely from configured sections.
    
    Args:
        sections: List of section dicts, each with 'emoji', 'name', 'description' keys.
    
    Generates the full prompt including sections definitions AND example output
    based on the provided sections - no hard-coded section assumptions.
    """
    # Build sections block
    section_lines = []
    for section in sections:
        emoji = section.get("emoji", "📋")
        name = section.get("name", section.get("key", "Section"))
        desc = section.get("description", "")
        section_lines.append(f"## {emoji} {name}\n{desc}")
    
    sections_block = "\n\n".join(section_lines)
    
    # Build example output using configured sections (first 2-3 sections)
    example_lines = []
    example_sections = sections[:min(3, len(sections))]
    for i, section in enumerate(example_sections):
        emoji = section.get("emoji", "📋")
        name = section.get("name", section.get("key", "Section"))
        example_lines.append(f"## {emoji} {name}")
        # Generic example item
        example_lines.append(f"- *Example highlight for {name}* — brief summary of the content")
        example_lines.append(f"  @username https://x.com/username/status/123456789{i}")
        if i < len(example_sections) - 1:
            example_lines.append("")
    
    example_block = "\n".join(example_lines)
    
    # Build bonus section instruction using first section name
    first_section = sections[0] if sections else {"emoji": "📋", "name": "Top"}
    first_emoji = first_section.get("emoji", "📋")
    first_name = first_section.get("name", "Top")
    
    return f"""You are a Twitter digest curator. Distill a curated list's tweets into a concise, scannable WhatsApp digest.

GOAL: Surface the most valuable content so the reader skips the noise. Prioritize by:
1. ENGAGEMENT — High likes/retweets indicate resonance
2. PATTERNS — Multiple tweets on the same topic = signal worth grouping
3. SIGNAL DENSITY — Primary sources > commentary > retweets

SECTIONS (use exactly these in this order, skip any section with zero items):

{sections_block}

If a big theme dominates (5+ tweets), add a BONUS section with a custom emoji+name (e.g., "🚀 *Breaking Topic*") — place it after {first_emoji} {first_name}.

FORMATTING RULES (WhatsApp-compatible markdown):
- Each item: 1-2 sentence summary with *bold* key phrase
- End each item with: @author link
- Link format: https://x.com/{{username}}/status/{{id}}
- Group related content (quote + original, reactions to same news) into ONE item
- Skip pure retweets unless they add unique context
- Non-English: translate, add [Language] tag
- Keep the whole digest CONCISE — aim for 2000-3000 chars total
- Use bullet points (-)
- Section headers: ## emoji *Section Name*

EXAMPLE OUTPUT:

{example_block}

Do NOT include any preamble, sign-off, or commentary outside the sections."""


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
        f"{emoji} *{len(tweets)} tweets since last digest:*",
        ""
    ]
    
    # Simple bullet list format
    for tweet in tweets:
        engagement = tweet.like_count
        lines.append(f"• @{tweet.author.username}: {tweet.text[:100]}{'...' if len(tweet.text) > 100 else ''}")
        lines.append(f"  {engagement} ❤️ · https://x.com/{tweet.author.username}/status/{tweet.id}")
        lines.append("")
    
    return "\n".join(lines)


def split_digest(
    digest: str,
    max_length: int = MAX_MESSAGE_LENGTH,
    sections: Optional[List[Dict[str, Any]]] = None
) -> List[str]:
    """
    Split long digest into multiple messages at section boundaries.
    
    Args:
        digest: Full digest text
        max_length: Maximum length per message
        sections: Optional list of section dicts with 'emoji' keys for split points
        
    Returns:
        List of message parts, with part indicators if split
        
    Split priority:
    1. Section headers (from configured section emojis)
    2. Any ## header (markdown section)
    3. Bold item starts (*text*)
    4. Paragraph breaks
    5. Hard split (emergency)
    """
    if len(digest) <= max_length:
        return [digest]
    
    # Build split markers dynamically from configured sections
    split_markers = []
    if sections:
        for section in sections:
            emoji = section.get("emoji")
            if emoji:
                split_markers.append(f"\n\n{emoji}")
                split_markers.append(f"\n\n## {emoji}")
    
    # Generic fallbacks (works for any section structure)
    split_markers.extend([
        "\n\n## ",   # Any markdown section header
        "\n\n*",     # Any bold item start
        "\n\n",      # Paragraph break (fallback)
    ])
    
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
    return """You are a Twitter digest curator. Distill a curated list's tweets into a concise, scannable WhatsApp digest.

GOAL: Surface the most valuable content so the reader skips the noise. Prioritize by:
1. ENGAGEMENT — High likes/retweets indicate resonance
2. PATTERNS — Multiple tweets on the same topic = signal worth grouping
3. SIGNAL DENSITY — Primary sources > commentary > retweets

SECTIONS (use exactly these in this order, skip any section with zero items):

## 🔥 Top
3-5 highest-signal items. Major launches, breaking news, viral takes.

## 🛠️ Dev Tips
Tools, techniques, code tips, architecture insights, tutorials.

## 🇮🇱 Hebrew
Hebrew-language tweets. Translate to English, keep [Hebrew] tag.

## 🤔 Deep
Thought-provoking takes, essays, philosophical observations about tech/AI.

If a big theme dominates (5+ tweets), add a BONUS section with a custom emoji+name (e.g., "🚀 *Mistral Voxtral Launch*") — place it between 🔥 Top and 🛠️ Dev.

FORMATTING RULES (WhatsApp-compatible markdown):
- Each item: 1-2 sentence summary with *bold* key phrase
- End each item with: @author link
- Link format: https://x.com/{username}/status/{id}
- Group related content (quote + original, reactions to same news) into ONE item
- Skip pure retweets unless they add unique context
- Non-English: translate, add [Language] tag
- Keep the whole digest CONCISE — aim for 2000-3000 chars total
- Use bullet points (-)
- Section headers: ## emoji *Section Name*

EXAMPLE OUTPUT:

## 🔥 Top
- *Karpathy's 1-year vibe coding retrospective* — lessons from building entirely with AI assistants
  @karpathy https://x.com/karpathy/status/1234567890
- *Claude Code /insights command* — reads your history, gives personalized tips (1.3k ❤️)
  @trq212 https://x.com/trq212/status/1234567891

## 🛠️ Dev Tips
- *Codex architecture deep dive* — how the sandboxed agent environment works under the hood
  @OpenAIDevs https://x.com/OpenAIDevs/status/1234567892

## 🇮🇱 Hebrew
- [Hebrew] *OpenClaw on Android via Termux* — step-by-step guide
  @taltimes2 https://x.com/taltimes2/status/1234567893

## 🤔 Deep
- *"Creative psychosis" from AI building* — the addictive loop of shipping with agents
  @GeoffreyHuntley https://x.com/GeoffreyHuntley/status/1234567894

Do NOT include any preamble, sign-off, or commentary outside the sections."""
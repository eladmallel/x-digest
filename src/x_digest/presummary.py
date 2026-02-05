"""
Pre-summarization logic for x-digest.

Handles the decision logic for when content needs pre-summarization and
builds the appropriate prompts for the LLM. Supports individual long tweets,
quote chains, and multi-tweet threads.

Pre-summarization reduces token usage in the main digest generation by
condensing long content while preserving key insights and author perspective.
"""

from typing import List, Dict, Tuple, Union, Optional
from .models import Tweet, calculate_content_length
from .classify import reconstruct_threads
from .llm.base import LLMProvider
from .errors import LLMError, ErrorCode


def should_presummary(content: Union[Tweet, List[Tweet]], config: Optional[Dict] = None) -> bool:
    """
    Determine if content needs pre-summarization.
    
    Args:
        content: Single tweet or list of tweets (thread)
        config: Configuration with pre-summarization thresholds
        
    Returns:
        True if content should be pre-summarized
        
    Triggers:
    - Tweet text > 500 characters
    - Quote tweet where quoted content > 300 characters
    - Thread with 2+ tweets
    - Combined content > 600 characters
    """
    if config is None:
        config = _get_default_presummary_config()
    
    presummary_config = config.get("pre_summarization", {})
    
    if isinstance(content, list):
        # Thread
        if len(content) >= presummary_config.get("thread_min_tweets", 2):
            return True
        
        # Single tweet thread - check length
        if len(content) == 1:
            return should_presummary(content[0], config)
        
        return False
    
    # Single tweet
    tweet = content
    
    # Check main tweet length
    if len(tweet.text) > presummary_config.get("long_tweet_chars", 500):
        return True
    
    # Check quote length
    if tweet.quoted_tweet:
        quoted_length = len(tweet.quoted_tweet.text)
        if quoted_length > presummary_config.get("long_quote_chars", 300):
            return True
    
    # Check combined length
    total_length = calculate_content_length(tweet)
    if total_length > presummary_config.get("long_combined_chars", 600):
        return True
    
    return False


def build_presummary_prompt(content: str, content_type: str, author: str) -> str:
    """
    Build pre-summarization prompt for LLM.
    
    Args:
        content: Full content to summarize
        content_type: "long_tweet" | "thread" | "quote_chain"
        author: Author username (without @)
        
    Returns:
        Formatted prompt string
    """
    char_count = len(content)
    
    # Count tweets if it's a thread
    if content_type == "thread":
        tweet_count = content.count("\n---\n") + 1  # Simple heuristic
        length_desc = f"{char_count} chars / {tweet_count} tweets"
    else:
        length_desc = f"{char_count} chars"
    
    prompt = f"""You are summarizing Twitter content for a digest. Preserve the key insights in detail.

CONTENT TYPE: {content_type}
AUTHOR: @{author}
ORIGINAL LENGTH: {length_desc}

CONTENT:
{content}

INSTRUCTIONS:
- Write 2 paragraphs (4-6 sentences total)
- First paragraph: core message, main argument, key claims
- Second paragraph: supporting details, specific numbers, recommendations, implications
- Preserve the author's perspective and tone
- Keep technical details if present
- Note what's opinion vs fact where relevant

OUTPUT: Just the summary, no preamble."""

    return prompt


def presummary_tweets(
    tweets: List[Tweet], 
    llm_provider: LLMProvider,
    config: Optional[Dict] = None
) -> List[Tuple[Tweet, Optional[str]]]:
    """
    Run pre-summarization on tweets that need it.
    
    Args:
        tweets: List of tweets to process
        llm_provider: LLM provider for summarization
        config: Configuration with thresholds
        
    Returns:
        List of (tweet, summary) tuples. Summary is None if not pre-summarized.
        
    This function handles failures gracefully - if LLM fails for a tweet,
    it returns None for that summary but continues processing others.
    """
    if config is None:
        config = _get_default_presummary_config()
    
    # Check if pre-summarization is disabled
    presummary_config = config.get("pre_summarization", {})
    if not presummary_config.get("enabled", True):
        # Return all tweets with None summaries
        return [(tweet, None) for tweet in tweets]
    
    # Reconstruct threads first
    threads = reconstruct_threads(tweets)
    
    results = []
    
    for conv_id, thread in threads.items():
        if len(thread) == 1:
            # Single tweet - check if it needs presummary
            tweet = thread[0]
            if should_presummary(tweet, config):
                summary = _summarize_single_tweet(tweet, llm_provider)
            else:
                summary = None
            results.append((tweet, summary))
        else:
            # Multi-tweet thread - pass the whole thread to should_presummary
            if should_presummary(thread, config):
                thread_summary = _summarize_thread(thread, llm_provider)
                # Apply the same summary to all tweets in thread  
                for tweet in thread:
                    results.append((tweet, thread_summary))
            else:
                # Thread doesn't need summarization
                for tweet in thread:
                    results.append((tweet, None))
    
    return results


def _summarize_single_tweet(tweet: Tweet, llm_provider: LLMProvider) -> Optional[str]:
    """Summarize a single tweet (possibly with quote)."""
    try:
        # Build content including quote if present
        content = tweet.text
        content_type = "long_tweet"
        
        if tweet.quoted_tweet:
            content += f"\n\nQUOTED CONTENT:\n{tweet.quoted_tweet.text}"
            content += f"\n(Originally by @{tweet.quoted_tweet.author.username})"
            content_type = "quote_chain"
        
        prompt = build_presummary_prompt(content, content_type, tweet.author.username)
        
        summary = llm_provider.generate(prompt, system="")
        return summary.strip() if summary else None
        
    except LLMError:
        # Log warning but don't fail the whole batch
        return None


def _summarize_thread(thread: List[Tweet], llm_provider: LLMProvider) -> Optional[str]:
    """Summarize a multi-tweet thread."""
    try:
        # Build thread content
        content_parts = []
        for i, tweet in enumerate(thread, 1):
            content_parts.append(f"Tweet {i}: {tweet.text}")
        
        content = "\n---\n".join(content_parts)
        author = thread[0].author.username  # Use first tweet's author
        
        prompt = build_presummary_prompt(content, "thread", author)
        
        summary = llm_provider.generate(prompt, system="")
        return summary.strip() if summary else None
        
    except LLMError:
        # Log warning but don't fail the whole batch
        return None


def _get_default_presummary_config() -> Dict:
    """Get default pre-summarization configuration."""
    return {
        "pre_summarization": {
            "enabled": True,
            "long_tweet_chars": 500,
            "long_quote_chars": 300,
            "long_combined_chars": 600,
            "thread_min_tweets": 2,
            "max_summary_tokens": 300
        }
    }
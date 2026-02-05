"""
Tweet classification and thread reconstruction.

Provides functions for:
- Classifying tweets by type (standalone, thread, quote, reply, retweet)
- Reconstructing threads from conversation IDs
- Determining thread completeness
- Deduplicating quote tweets

The classification system enables intelligent pre-processing by identifying
content that needs special handling (threads for summarization, quotes for
deduplication, etc.).
"""

from enum import Enum
from typing import List, Dict, Tuple
from datetime import datetime

from .models import Tweet
from .utils import parse_twitter_date


class TweetType(Enum):
    """Classification of tweet types."""
    STANDALONE = "standalone"  # Single tweet, not part of thread
    THREAD = "thread"  # Part of a multi-tweet thread
    QUOTE = "quote"  # Quote tweet
    REPLY = "reply"  # Reply to another tweet (but not in our batch)
    RETWEET = "retweet"  # Pure retweet (RT @user:...)


def classify_tweet(tweet: Tweet) -> TweetType:
    """
    Classify a tweet by its type.
    
    Args:
        tweet: Tweet object to classify
        
    Returns:
        TweetType enum value
        
    Detection logic:
    - Retweet: text starts with "RT @"
    - Quote: has quotedTweet field
    - Reply: has inReplyToStatusId
    - Thread/Standalone: determined by context (see reconstruct_threads)
    """
    # Check for retweet
    if tweet.text.startswith("RT @"):
        return TweetType.RETWEET
    
    # Check for quote tweet
    if tweet.quoted_tweet is not None:
        return TweetType.QUOTE
    
    # Check for reply
    if tweet.in_reply_to_status_id is not None:
        return TweetType.REPLY
    
    # Standalone (thread classification requires context)
    return TweetType.STANDALONE


def reconstruct_threads(tweets: List[Tweet]) -> Dict[str, List[Tweet]]:
    """
    Group tweets into threads by conversation_id and sort chronologically.
    
    Args:
        tweets: List of Tweet objects
        
    Returns:
        Dictionary mapping conversation_id to sorted list of tweets
        
    The returned threads are sorted by created_at within each conversation.
    Single tweets are also included as single-item "threads" for consistency.
    """
    threads: Dict[str, List[Tweet]] = {}
    
    # Group by conversation ID
    for tweet in tweets:
        conv_id = tweet.conversation_id
        if conv_id not in threads:
            threads[conv_id] = []
        threads[conv_id].append(tweet)
    
    # Sort tweets within each thread by creation time
    for conv_id, thread_tweets in threads.items():
        # Parse datetime for sorting
        try:
            threads[conv_id] = sorted(
                thread_tweets,
                key=lambda t: parse_twitter_date(t.created_at)
            )
        except Exception:
            # Fallback: keep original order if date parsing fails
            pass
    
    return threads


def classify_thread_completeness(thread: List[Tweet]) -> str:
    """
    Determine if we have a complete thread or partial.
    
    Args:
        thread: List of tweets in chronological order
        
    Returns:
        "complete" | "partial_with_root" | "partial_no_root"
        
    Logic:
    - complete: Has root tweet and no gaps in reply chain
    - partial_with_root: Has root but missing some replies
    - partial_no_root: Started mid-thread, missing root
    """
    if not thread:
        return "complete"  # Empty thread is technically complete
    
    if len(thread) == 1:
        return "complete"  # Single tweet is always complete
    
    # Check if we have the root (conversation_id == tweet.id)
    has_root = any(t.id == t.conversation_id for t in thread)
    
    if not has_root:
        return "partial_no_root"
    
    # Check for gaps in reply chain
    tweet_ids = {t.id for t in thread}
    
    gaps = []
    for tweet in thread:
        if tweet.in_reply_to_status_id:
            # This tweet replies to something
            if tweet.in_reply_to_status_id not in tweet_ids:
                # The thing it replies to is not in our batch
                gaps.append(tweet.in_reply_to_status_id)
    
    if gaps:
        return "partial_with_root"
    else:
        return "complete"


def dedupe_quotes(tweets: List[Tweet]) -> List[Tweet]:
    """
    Remove standalone tweets that are quoted by another tweet in the batch.
    
    Args:
        tweets: List of Tweet objects
        
    Returns:
        Filtered list with quoted tweets removed
        
    Logic: If tweet A quotes tweet B, and both are in the batch,
    remove standalone tweet B (keep the quote tweet A which includes the content).
    """
    # Find all tweet IDs that are quoted by other tweets in this batch
    tweet_ids_in_batch = {t.id for t in tweets}
    quoted_ids = set()
    
    for tweet in tweets:
        if tweet.quoted_tweet and tweet.quoted_tweet.id in tweet_ids_in_batch:
            quoted_ids.add(tweet.quoted_tweet.id)
    
    # Keep tweets that are NOT quoted by another tweet in this batch
    return [tweet for tweet in tweets if tweet.id not in quoted_ids]


def categorize_tweets(tweets: List[Tweet]) -> Dict[str, List[Tweet]]:
    """
    Categorize tweets for different processing pipelines.
    
    Args:
        tweets: List of Tweet objects
        
    Returns:
        Dictionary with categorized tweets:
        - "standalone": Single tweets
        - "threads": Multi-tweet threads 
        - "quotes": Quote tweets
        - "replies": Replies (not in threads)
        - "retweets": Pure retweets
    """
    # First reconstruct threads
    threads = reconstruct_threads(tweets)
    
    # Separate single tweets from multi-tweet threads
    single_tweets = [tweets for tweets in threads.values() if len(tweets) == 1]
    multi_tweet_threads = [tweets for tweets in threads.values() if len(tweets) > 1]
    
    # Classify single tweets
    standalone = []
    quotes = []
    replies = []
    retweets = []
    
    for thread in single_tweets:
        tweet = thread[0]  # Single tweet
        tweet_type = classify_tweet(tweet)
        
        if tweet_type == TweetType.QUOTE:
            quotes.append(tweet)
        elif tweet_type == TweetType.REPLY:
            replies.append(tweet)
        elif tweet_type == TweetType.RETWEET:
            retweets.append(tweet)
        else:
            standalone.append(tweet)
    
    # Flatten multi-tweet threads back to tweet lists
    thread_tweets = []
    for thread in multi_tweet_threads:
        thread_tweets.extend(thread)
    
    return {
        "standalone": standalone,
        "threads": multi_tweet_threads,  # List of thread lists
        "quotes": quotes,
        "replies": replies,
        "retweets": retweets
    }


def get_thread_stats(threads: Dict[str, List[Tweet]]) -> Dict[str, int]:
    """
    Get statistics about thread reconstruction.
    
    Returns:
        Dictionary with counts and metrics
    """
    total_threads = len(threads)
    single_tweets = sum(1 for t in threads.values() if len(t) == 1)
    multi_tweet_threads = total_threads - single_tweets
    total_tweets = sum(len(t) for t in threads.values())
    
    # Analyze completeness
    complete = 0
    partial_with_root = 0
    partial_no_root = 0
    
    for thread in threads.values():
        completeness = classify_thread_completeness(thread)
        if completeness == "complete":
            complete += 1
        elif completeness == "partial_with_root":
            partial_with_root += 1
        else:
            partial_no_root += 1
    
    return {
        "total_threads": total_threads,
        "single_tweets": single_tweets,
        "multi_tweet_threads": multi_tweet_threads,
        "total_tweets": total_tweets,
        "complete_threads": complete,
        "partial_with_root": partial_with_root,
        "partial_no_root": partial_no_root
    }


# Date parsing utility moved to utils.py
"""Data collectors for various platforms."""
from .base import BaseCollector, Post
from .hackernews_collector import HackerNewsCollector
from .reddit_collector import RedditCollector

__all__ = ["BaseCollector", "Post", "HackerNewsCollector", "RedditCollector"]

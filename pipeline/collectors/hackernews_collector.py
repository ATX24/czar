"""Hacker News collector using Firebase REST API."""
import logging
from datetime import datetime
from typing import Any, Optional, List, Dict, Set

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseCollector, Post

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsCollector(BaseCollector):
    """Collector for Hacker News stories."""

    source_name = "hn"

    def __init__(
        self,
        top_stories_limit: int = 500,
        new_stories_limit: int = 200
    ):
        self.top_stories_limit = top_stories_limit
        self.new_stories_limit = new_stories_limit
        self.client = httpx.Client(timeout=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    def _fetch_json(self, url: str) -> Any:
        """Fetch JSON from HN API with retry."""
        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def _fetch_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single HN item."""
        try:
            return self._fetch_json(f"{HN_API_BASE}/item/{item_id}.json")
        except Exception as e:
            logger.warning(f"Failed to fetch HN item {item_id}: {e}")
            return None

    def _item_to_post(self, item: Dict[str, Any]) -> Optional[Post]:
        """Convert HN item to Post model."""
        if not item or item.get("deleted") or item.get("dead"):
            return None

        item_type = item.get("type", "")
        if item_type not in ("story", "job"):
            return None

        item_id = item.get("id")
        if not item_id:
            return None

        # Build text from title + optional text content
        title = item.get("title", "")
        text_content = item.get("text", "")
        full_text = f"{title}\n{text_content}".strip() if text_content else title

        if not full_text:
            return None

        # Calculate score from points and comments
        points = item.get("score", 0)
        comments = item.get("descendants", 0)
        engagement_score = points + (comments * 2)  # Weight comments higher

        created_at = datetime.utcfromtimestamp(item.get("time", 0))

        return Post(
            id=f"hn_{item_id}",
            source=self.source_name,
            created_at=created_at,
            text=full_text,
            url=item.get("url"),
            score=self.normalize_score(engagement_score),
            metadata={
                "hn_id": item_id,
                "type": item_type,
                "by": item.get("by"),
                "points": points,
                "comments": comments,
                "hn_url": f"https://news.ycombinator.com/item?id={item_id}"
            }
        )

    def fetch(self, since: datetime) -> List[Post]:
        """Fetch HN stories since the given datetime."""
        posts: List[Post] = []
        seen_ids: Set[int] = set()

        # Fetch top stories
        try:
            top_ids = self._fetch_json(f"{HN_API_BASE}/topstories.json")
            top_ids = top_ids[:self.top_stories_limit] if top_ids else []
        except Exception as e:
            logger.error(f"Failed to fetch HN top stories: {e}")
            top_ids = []

        # Fetch new stories
        try:
            new_ids = self._fetch_json(f"{HN_API_BASE}/newstories.json")
            new_ids = new_ids[:self.new_stories_limit] if new_ids else []
        except Exception as e:
            logger.error(f"Failed to fetch HN new stories: {e}")
            new_ids = []

        # Combine and dedupe
        all_ids = []
        for item_id in top_ids + new_ids:
            if item_id not in seen_ids:
                seen_ids.add(item_id)
                all_ids.append(item_id)

        logger.info(f"Fetching {len(all_ids)} HN items")

        for item_id in all_ids:
            item = self._fetch_item(item_id)
            if not item:
                continue

            post = self._item_to_post(item)
            if not post:
                continue

            # Filter by time
            if post.created_at < since:
                continue

            posts.append(post)

        logger.info(f"Collected {len(posts)} HN posts since {since}")
        return posts

    def close(self) -> None:
        """Close HTTP client."""
        self.client.close()

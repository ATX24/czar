"""Reddit collector using PRAW."""
import logging
from datetime import datetime
from typing import List, Set

import praw
from praw.models import Submission

from .base import BaseCollector, Post

logger = logging.getLogger(__name__)


class RedditCollector(BaseCollector):
    """Collector for Reddit posts."""

    source_name = "reddit"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        subreddits: List[str],
        posts_per_subreddit: int = 100
    ):
        self.subreddits = subreddits
        self.posts_per_subreddit = posts_per_subreddit

        self.reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent
        )

    def _submission_to_post(self, submission: Submission) -> Post:
        """Convert Reddit submission to Post model."""
        # Combine title and selftext
        text = submission.title
        if submission.selftext:
            text = f"{text}\n\n{submission.selftext}"

        # Calculate engagement score
        # Reddit score + comments weighted
        engagement = submission.score + (submission.num_comments * 3)

        created_at = datetime.utcfromtimestamp(submission.created_utc)

        return Post(
            id=f"reddit_{submission.id}",
            source=self.source_name,
            created_at=created_at,
            text=text,
            url=submission.url if not submission.is_self else f"https://reddit.com{submission.permalink}",
            score=self.normalize_score(engagement),
            metadata={
                "reddit_id": submission.id,
                "subreddit": submission.subreddit.display_name,
                "author": str(submission.author) if submission.author else "[deleted]",
                "upvotes": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "num_comments": submission.num_comments,
                "is_self": submission.is_self,
                "permalink": f"https://reddit.com{submission.permalink}",
                "flair": submission.link_flair_text
            }
        )

    def fetch(self, since: datetime) -> List[Post]:
        """Fetch Reddit posts since the given datetime."""
        posts: List[Post] = []
        seen_ids: Set[str] = set()

        since_timestamp = since.timestamp()

        for subreddit_name in self.subreddits:
            try:
                subreddit = self.reddit.subreddit(subreddit_name)

                # Fetch from both hot and new
                for sort_type in ["hot", "new"]:
                    if sort_type == "hot":
                        submissions = subreddit.hot(limit=self.posts_per_subreddit)
                    else:
                        submissions = subreddit.new(limit=self.posts_per_subreddit)

                    for submission in submissions:
                        # Skip if already seen
                        if submission.id in seen_ids:
                            continue
                        seen_ids.add(submission.id)

                        # Skip if too old
                        if submission.created_utc < since_timestamp:
                            continue

                        try:
                            post = self._submission_to_post(submission)
                            posts.append(post)
                        except Exception as e:
                            logger.warning(
                                f"Failed to process submission {submission.id}: {e}"
                            )

            except Exception as e:
                logger.error(f"Failed to fetch from r/{subreddit_name}: {e}")
                continue

        logger.info(f"Collected {len(posts)} Reddit posts since {since}")
        return posts

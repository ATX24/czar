"""Velocity scoring for topics."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, List, Dict

import numpy as np

from store.models import Post, Topic, TopicScore

logger = logging.getLogger(__name__)


def _to_naive(dt: datetime) -> datetime:
    """Convert datetime to naive (remove timezone info)."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


class VelocityScorer:
    """
    Scores topics by velocity (rate of change) rather than raw volume.

    A topic with 50 posts/day that grew from 5 posts/day is more signal-rich
    than a topic with 10,000 posts/day that has been flat for months.
    """

    def __init__(
        self,
        window_24h_hours: int = 24,
        window_7d_hours: int = 168,
        baseline_days: int = 30,
        recency_weight_24h: float = 0.5,
        recency_weight_7d: float = 0.5,
        inflection_threshold: float = 2.0,
        inflection_bonus: float = 0.3
    ):
        self.window_24h = timedelta(hours=window_24h_hours)
        self.window_7d = timedelta(hours=window_7d_hours)
        self.baseline_period = timedelta(days=baseline_days)
        self.recency_weight_24h = recency_weight_24h
        self.recency_weight_7d = recency_weight_7d
        self.inflection_threshold = inflection_threshold
        self.inflection_bonus = inflection_bonus

    def _get_posts_for_topic(
        self,
        topic: Topic,
        posts: List[Post]
    ) -> List[Post]:
        """Get posts that belong to a topic."""
        post_id_set = set(topic.post_ids)
        return [p for p in posts if p.id in post_id_set]

    def _compute_velocity(
        self,
        posts: List[Post],
        window_start: datetime,
        window_end: datetime
    ) -> float:
        """
        Compute velocity (weighted engagement change rate) for a time window.

        Velocity = sum(post_score * engagement) / window_hours
        """
        ws = _to_naive(window_start)
        we = _to_naive(window_end)

        window_posts = [
            p for p in posts
            if ws <= _to_naive(p.created_at) < we
        ]

        if not window_posts:
            return 0.0

        # Sum of engagement-weighted scores
        total_engagement = sum(p.score for p in window_posts)

        # Volume component
        volume = len(window_posts)

        # Combined velocity: volume + weighted engagement
        window_hours = (window_end - window_start).total_seconds() / 3600
        velocity = (volume + total_engagement * 10) / max(window_hours, 1)

        return velocity

    def _compute_zscore(
        self,
        value: float,
        baseline_values: List[float]
    ) -> float:
        """Compute z-score relative to baseline."""
        if len(baseline_values) < 2:
            return 0.0

        mean = np.mean(baseline_values)
        std = np.std(baseline_values)

        if std < 0.001:
            return 0.0

        return (value - mean) / std

    def _detect_driver(
        self,
        posts: List[Post]
    ) -> Optional[str]:
        """
        Detect what's driving a topic's inflection.

        Scans source posts for signals:
        - new_paper: URL matches arxiv.org, paperswithcode.com
        - new_repo: GitHub collector sees new high-velocity repo
        - benchmark: text matches SOTA, beats, surpasses
        - product_launch: URL matches ProductHunt, TechCrunch, etc.
        """
        paper_domains = ["arxiv.org", "paperswithcode.com", "openreview.net"]
        launch_domains = ["producthunt.com", "techcrunch.com", "venturebeat.com"]
        benchmark_patterns = ["sota", "state-of-the-art", "beats", "surpasses",
                              "outperforms", "new record", "benchmark"]

        driver_signals: Dict[str, int] = {
            "new_paper": 0,
            "new_repo": 0,
            "benchmark": 0,
            "product_launch": 0
        }

        for post in posts:
            url = (post.url or "").lower()
            text = post.text.lower()

            # Check for papers
            if any(domain in url for domain in paper_domains):
                driver_signals["new_paper"] += 1

            # Check for GitHub repos
            if "github.com" in url and post.source != "github":
                driver_signals["new_repo"] += 1

            # Check for product launches
            if any(domain in url for domain in launch_domains):
                driver_signals["product_launch"] += 1
            if any(kw in text for kw in ["announces", "launches", "releases", "introducing"]):
                driver_signals["product_launch"] += 1

            # Check for benchmarks
            if any(pattern in text for pattern in benchmark_patterns):
                driver_signals["benchmark"] += 1

        # Return the strongest signal
        if not any(driver_signals.values()):
            return None

        return max(driver_signals, key=lambda k: driver_signals[k])

    def score_topics(
        self,
        topics: List[Topic],
        posts: List[Post],
        baseline_posts: List[Post],
        reference_time: Optional[datetime] = None
    ) -> List[TopicScore]:
        """
        Score all topics by velocity.

        Args:
            topics: List of Topic objects to score
            posts: Posts from the current scoring window
            baseline_posts: Posts from the baseline period (for z-score calculation)
            reference_time: Time reference for windows (defaults to now)

        Returns:
            List of TopicScore objects
        """
        if reference_time is None:
            reference_time = datetime.utcnow()

        scores: List[TopicScore] = []

        for topic in topics:
            topic_posts = self._get_posts_for_topic(topic, posts)

            if not topic_posts:
                continue

            # Compute 24h velocity
            velocity_24h = self._compute_velocity(
                topic_posts,
                reference_time - self.window_24h,
                reference_time
            )

            # Compute 7d velocity
            velocity_7d = self._compute_velocity(
                topic_posts,
                reference_time - self.window_7d,
                reference_time
            )

            # Compute baseline velocities for z-score
            # Sample velocities at daily intervals over baseline period
            baseline_topic_posts = self._get_posts_for_topic(topic, baseline_posts)
            baseline_velocities = []

            for days_ago in range(1, 31):
                window_end = reference_time - timedelta(days=days_ago)
                window_start = window_end - timedelta(days=1)
                v = self._compute_velocity(baseline_topic_posts, window_start, window_end)
                baseline_velocities.append(v)

            # Z-scores
            zscore_24h = self._compute_zscore(velocity_24h, baseline_velocities)
            zscore_7d = self._compute_zscore(velocity_7d, baseline_velocities)

            # Combined velocity score (recency-weighted)
            velocity_score = (
                self.recency_weight_24h * zscore_24h +
                self.recency_weight_7d * zscore_7d
            )

            # Detect inflection
            # Inflection = z-score crosses threshold after being below for 7+ days
            is_inflection = zscore_24h >= self.inflection_threshold

            # Detect driver if inflecting
            driver = None
            if is_inflection:
                cutoff = reference_time - self.window_24h
                recent_posts = [
                    p for p in topic_posts
                    if _to_naive(p.created_at) >= _to_naive(cutoff)
                ]
                driver = self._detect_driver(recent_posts)

            # Apply inflection bonus
            if is_inflection:
                velocity_score += self.inflection_bonus

            scores.append(TopicScore(
                run_id=topic.run_id,
                topic_id=topic.topic_id,
                score_date=reference_time,
                velocity=velocity_score,
                novelty=0.0,  # Computed by novelty detector
                volume=len(topic_posts),
                inflection=is_inflection,
                driver=driver
            ))

        # Sort by velocity score descending
        scores.sort(key=lambda s: s.velocity, reverse=True)

        logger.info(f"Scored {len(scores)} topics")
        return scores


class NoveltyDetector:
    """
    Detects novelty of topics compared to historical topics.

    Novelty = 1 - max_similarity to topics in last 30 days.
    """

    def __init__(self, novelty_weight: float = 0.4):
        self.novelty_weight = novelty_weight

    def compute_novelty(
        self,
        topic_embedding: List[float],
        historical_embeddings: List[List[float]]
    ) -> float:
        """
        Compute novelty score for a topic.

        Args:
            topic_embedding: Embedding of the current topic
            historical_embeddings: Embeddings of historical topics

        Returns:
            Novelty score in [0, 1] where 1 = completely new
        """
        if not historical_embeddings:
            return 1.0

        # Compute similarities
        topic_vec = np.array(topic_embedding)
        hist_vecs = np.array(historical_embeddings)

        # Normalize
        topic_norm = topic_vec / (np.linalg.norm(topic_vec) + 1e-10)
        hist_norms = hist_vecs / (np.linalg.norm(hist_vecs, axis=1, keepdims=True) + 1e-10)

        # Cosine similarity
        similarities = np.dot(hist_norms, topic_norm)
        max_similarity = np.max(similarities)

        # Novelty = 1 - max_similarity
        novelty = 1.0 - max_similarity
        return float(np.clip(novelty, 0, 1))

    def adjust_scores(
        self,
        scores: List[TopicScore],
        novelty_scores: Dict[int, float]
    ) -> List[TopicScore]:
        """
        Adjust velocity scores by novelty multiplier.

        Combined score = velocity × (0.6 + 0.4 × novelty)
        """
        for score in scores:
            novelty = novelty_scores.get(score.topic_id, 0.5)
            score.novelty = novelty

            # Apply novelty multiplier
            multiplier = 0.6 + self.novelty_weight * novelty
            score.velocity = score.velocity * multiplier

        # Re-sort after adjustment
        scores.sort(key=lambda s: s.velocity, reverse=True)

        return scores

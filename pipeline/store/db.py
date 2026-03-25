"""DuckDB database connection and operations."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, List, Union

import duckdb

from .models import Post, Topic, TopicScore


class Database:
    """DuckDB database manager for trend data."""

    def __init__(self, db_path: Union[Path, str]):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_posts (
                id VARCHAR PRIMARY KEY,
                source VARCHAR,
                collected_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ,
                text TEXT,
                url VARCHAR,
                score DOUBLE,
                metadata JSON
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                run_id VARCHAR,
                topic_id INTEGER,
                label VARCHAR,
                keywords JSON,
                post_ids JSON,
                created_at TIMESTAMPTZ,
                PRIMARY KEY (run_id, topic_id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS topic_scores (
                run_id VARCHAR,
                topic_id INTEGER,
                score_date DATE,
                velocity DOUBLE,
                novelty DOUBLE,
                volume INTEGER,
                inflection BOOLEAN,
                driver VARCHAR,
                PRIMARY KEY (run_id, topic_id, score_date)
            )
        """)

        # Create indexes for common queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_posts_source
            ON raw_posts(source)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_posts_created
            ON raw_posts(created_at)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_posts_collected
            ON raw_posts(collected_at)
        """)

    def insert_posts(self, posts: List[Post]) -> int:
        """Insert posts, skipping duplicates. Returns count of new posts."""
        if not posts:
            return 0

        new_count = 0
        for post in posts:
            try:
                self.conn.execute("""
                    INSERT INTO raw_posts
                    (id, source, collected_at, created_at, text, url, score, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    post.id,
                    post.source,
                    post.collected_at,
                    post.created_at,
                    post.text,
                    post.url,
                    post.score,
                    json.dumps(post.metadata)
                ])
                new_count += 1
            except duckdb.ConstraintException:
                # Duplicate, skip
                pass

        return new_count

    def get_posts_since(
        self,
        since: datetime,
        source: Optional[str] = None
    ) -> List[Post]:
        """Get all posts since a given datetime."""
        query = "SELECT * FROM raw_posts WHERE created_at >= ?"
        params: List[Any] = [since]

        if source:
            query += " AND source = ?"
            params.append(source)

        query += " ORDER BY created_at DESC"

        result = self.conn.execute(query, params).fetchall()
        columns = ["id", "source", "collected_at", "created_at",
                   "text", "url", "score", "metadata"]

        posts = []
        for row in result:
            data = dict(zip(columns, row))
            if isinstance(data["metadata"], str):
                data["metadata"] = json.loads(data["metadata"])
            posts.append(Post(**data))

        return posts

    def get_posts_in_window(
        self,
        start: datetime,
        end: datetime,
        source: Optional[str] = None
    ) -> List[Post]:
        """Get posts within a time window."""
        query = "SELECT * FROM raw_posts WHERE created_at >= ? AND created_at < ?"
        params: List[Any] = [start, end]

        if source:
            query += " AND source = ?"
            params.append(source)

        result = self.conn.execute(query, params).fetchall()
        columns = ["id", "source", "collected_at", "created_at",
                   "text", "url", "score", "metadata"]

        posts = []
        for row in result:
            data = dict(zip(columns, row))
            if isinstance(data["metadata"], str):
                data["metadata"] = json.loads(data["metadata"])
            posts.append(Post(**data))

        return posts

    def insert_topics(self, topics: List[Topic]) -> None:
        """Insert topic modeling results."""
        for topic in topics:
            self.conn.execute("""
                INSERT OR REPLACE INTO topics
                (run_id, topic_id, label, keywords, post_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                topic.run_id,
                topic.topic_id,
                topic.label,
                json.dumps(topic.keywords),
                json.dumps(topic.post_ids),
                topic.created_at
            ])

    def get_topics_for_run(self, run_id: str) -> List[Topic]:
        """Get all topics from a specific run."""
        result = self.conn.execute("""
            SELECT * FROM topics WHERE run_id = ?
            ORDER BY topic_id
        """, [run_id]).fetchall()

        columns = ["run_id", "topic_id", "label", "keywords",
                   "post_ids", "created_at"]

        topics = []
        for row in result:
            data = dict(zip(columns, row))
            if isinstance(data["keywords"], str):
                data["keywords"] = json.loads(data["keywords"])
            if isinstance(data["post_ids"], str):
                data["post_ids"] = json.loads(data["post_ids"])
            topics.append(Topic(**data))

        return topics

    def insert_topic_scores(self, scores: List[TopicScore]) -> None:
        """Insert topic scores."""
        for score in scores:
            self.conn.execute("""
                INSERT OR REPLACE INTO topic_scores
                (run_id, topic_id, score_date, velocity, novelty,
                 volume, inflection, driver)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                score.run_id,
                score.topic_id,
                score.score_date,
                score.velocity,
                score.novelty,
                score.volume,
                score.inflection,
                score.driver
            ])

    def get_recent_topics(self, days: int = 30) -> List[Topic]:
        """Get topics from the last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = self.conn.execute("""
            SELECT * FROM topics
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """, [cutoff]).fetchall()

        columns = ["run_id", "topic_id", "label", "keywords",
                   "post_ids", "created_at"]

        topics = []
        for row in result:
            data = dict(zip(columns, row))
            if isinstance(data["keywords"], str):
                data["keywords"] = json.loads(data["keywords"])
            if isinstance(data["post_ids"], str):
                data["post_ids"] = json.loads(data["post_ids"])
            topics.append(Topic(**data))

        return topics

    def get_post_count(self, source: Optional[str] = None) -> int:
        """Get total post count, optionally filtered by source."""
        if source:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM raw_posts WHERE source = ?",
                [source]
            ).fetchone()
        else:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM raw_posts"
            ).fetchone()

        return result[0] if result else 0

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

"""Scheduler for trend intelligence pipeline."""
import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add pipeline directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from apscheduler.schedulers.blocking import BlockingScheduler

import config
from collectors import HackerNewsCollector
from store import Database
from store.models import Post as StorePost
from analysis.topic_modeler import TopicModeler
from analysis.velocity_scorer import VelocityScorer, NoveltyDetector
from output.digest_generator import DigestGenerator
from output.html_report import HTMLReportGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class TrendPipeline:
    """Main pipeline orchestrator."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db = Database(db_path or config.DB_PATH)

        # Initialize collectors
        self.hn_collector = HackerNewsCollector(
            top_stories_limit=config.HN_TOP_STORIES_LIMIT,
            new_stories_limit=config.HN_NEW_STORIES_LIMIT
        )

        # Initialize pipeline components
        self.topic_modeler = TopicModeler(
            embedding_model=config.EMBEDDING_MODEL,
            min_topic_size=config.MIN_TOPIC_SIZE,
            top_n_keywords=config.TOP_N_KEYWORDS
        )

        self.velocity_scorer = VelocityScorer(
            window_24h_hours=config.WINDOW_24H_HOURS,
            window_7d_hours=config.WINDOW_7D_HOURS,
            baseline_days=config.BASELINE_DAYS,
            recency_weight_24h=config.RECENCY_WEIGHT_24H,
            recency_weight_7d=config.RECENCY_WEIGHT_7D,
            inflection_threshold=config.VELOCITY_ZSCORE_THRESHOLD,
            inflection_bonus=config.INFLECTION_BONUS
        )

        self.novelty_detector = NoveltyDetector(
            novelty_weight=config.NOVELTY_WEIGHT
        )

        self.digest_generator = DigestGenerator(
            top_n_themes=config.TOP_N_TOPICS,
            use_llm_summaries=config.USE_LLM_SUMMARIES,
            openrouter_api_key=config.OPENROUTER_API_KEY,
            openrouter_model=config.OPENROUTER_MODEL
        )

        self.html_generator = HTMLReportGenerator(
            output_dir=config.OUTPUTS_DIR
        )

    def collect(self, since: Optional[datetime] = None) -> int:
        """
        Run data collection from all sources.

        Returns:
            Number of new posts collected
        """
        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)

        logger.info(f"Starting collection since {since}")
        total_new = 0

        # Collect from HN
        try:
            hn_posts = self.hn_collector.fetch(since)
            store_posts = [
                StorePost(
                    id=p.id,
                    source=p.source,
                    collected_at=p.collected_at,
                    created_at=p.created_at,
                    text=p.text,
                    url=p.url,
                    score=p.score,
                    metadata=p.metadata
                )
                for p in hn_posts
            ]
            new_count = self.db.insert_posts(store_posts)
            total_new += new_count
            logger.info(f"Collected {new_count} new HN posts")
        except Exception as e:
            logger.error(f"HN collection failed: {e}")

        logger.info(f"Total new posts collected: {total_new}")
        return total_new

    def analyze(self) -> None:
        """Run topic modeling and scoring on recent posts."""
        now = datetime.utcnow()
        window_start = now - timedelta(days=7)
        baseline_start = now - timedelta(days=config.BASELINE_DAYS)

        logger.info("Starting analysis pipeline")

        # Get posts
        posts = self.db.get_posts_since(window_start)
        baseline_posts = self.db.get_posts_since(baseline_start)

        if len(posts) < config.MIN_TOPIC_SIZE:
            logger.warning(f"Not enough posts for analysis: {len(posts)}")
            return

        logger.info(f"Analyzing {len(posts)} posts from the last 7 days")

        # Topic modeling
        topics, post_topic_map = self.topic_modeler.fit_transform(posts)

        if not topics:
            logger.warning("No topics discovered")
            return

        # Store topics
        self.db.insert_topics(topics)

        # Velocity scoring
        scores = self.velocity_scorer.score_topics(
            topics, posts, baseline_posts, now
        )

        # Get topic embeddings for novelty detection
        topic_embeddings = self.topic_modeler.get_topic_embeddings()

        # Get historical topic embeddings (last 30 days)
        historical_topics = self.db.get_recent_topics(days=30)
        historical_embeddings = []
        for ht in historical_topics:
            # Re-embed historical keywords
            keywords_text = " ".join(ht.keywords[:10])
            emb = self.topic_modeler.embedding_model.encode(keywords_text).tolist()
            historical_embeddings.append(emb)

        # Compute novelty scores
        novelty_scores = {}
        for topic in topics:
            if topic.topic_id in topic_embeddings:
                novelty = self.novelty_detector.compute_novelty(
                    topic_embeddings[topic.topic_id],
                    historical_embeddings
                )
                novelty_scores[topic.topic_id] = novelty

        # Adjust scores by novelty
        scores = self.novelty_detector.adjust_scores(scores, novelty_scores)

        # Store scores
        self.db.insert_topic_scores(scores)

        logger.info(f"Analysis complete: {len(topics)} topics scored")

    def generate_digest(self) -> Optional[Path]:
        """Generate weekly HTML digest."""
        now = datetime.utcnow()
        week_start = now - timedelta(days=7)

        logger.info("Generating weekly digest")

        # Get recent data
        posts = self.db.get_posts_since(week_start)
        topics = self.db.get_recent_topics(days=7)

        if not topics:
            logger.warning("No topics to generate digest from")
            return None

        # Get scores for the most recent run
        if topics:
            run_id = topics[0].run_id
            # Re-score for digest (use latest scores)
            baseline_posts = self.db.get_posts_since(
                now - timedelta(days=config.BASELINE_DAYS)
            )
            scores = self.velocity_scorer.score_topics(
                topics, posts, baseline_posts, now
            )

            # Get novelty scores
            topic_embeddings = self.topic_modeler.get_topic_embeddings()
            historical_topics = self.db.get_recent_topics(days=30)
            historical_embeddings = []
            for ht in historical_topics:
                keywords_text = " ".join(ht.keywords[:10])
                emb = self.topic_modeler.embedding_model.encode(keywords_text).tolist()
                historical_embeddings.append(emb)

            novelty_scores = {}
            for topic in topics:
                if topic.topic_id in topic_embeddings:
                    novelty = self.novelty_detector.compute_novelty(
                        topic_embeddings[topic.topic_id],
                        historical_embeddings
                    )
                    novelty_scores[topic.topic_id] = novelty

            scores = self.novelty_detector.adjust_scores(scores, novelty_scores)
        else:
            scores = []

        # Generate digest
        digest = self.digest_generator.generate(
            topics=topics,
            scores=scores,
            posts=posts,
            date_range=(week_start, now)
        )

        # Generate HTML
        output_path = self.html_generator.generate(digest)

        logger.info(f"Digest generated: {output_path}")
        return output_path

    def run_full_pipeline(self) -> Optional[Path]:
        """Run the complete pipeline: collect, analyze, generate digest."""
        logger.info("Running full pipeline")

        # Collect last 7 days of data
        since = datetime.utcnow() - timedelta(days=7)
        self.collect(since)

        # Analyze
        self.analyze()

        # Generate digest
        return self.generate_digest()

    def close(self) -> None:
        """Clean up resources."""
        self.db.close()
        self.hn_collector.close()


def run_scheduled():
    """Run the pipeline on a schedule."""
    pipeline = TrendPipeline()
    scheduler = BlockingScheduler()

    # Collect every hour
    scheduler.add_job(
        lambda: pipeline.collect(datetime.utcnow() - timedelta(hours=2)),
        "interval",
        hours=1,
        id="collect"
    )

    # Analyze daily at 6 AM UTC
    scheduler.add_job(
        pipeline.analyze,
        "cron",
        hour=6,
        id="analyze"
    )

    # Generate digest weekly on Monday at 7 AM UTC
    scheduler.add_job(
        pipeline.generate_digest,
        "cron",
        day_of_week="mon",
        hour=7,
        id="digest"
    )

    logger.info("Starting scheduled pipeline")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        pipeline.close()


def main():
    parser = argparse.ArgumentParser(description="Trend Intelligence Pipeline")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run pipeline once and exit"
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Only run collection"
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Only run analysis"
    )
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="Only generate digest"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving (for testing)"
    )

    args = parser.parse_args()

    pipeline = TrendPipeline()

    try:
        if args.collect_only:
            since = datetime.utcnow() - timedelta(days=7)
            pipeline.collect(since)
        elif args.analyze_only:
            pipeline.analyze()
        elif args.digest_only:
            output = pipeline.generate_digest()
            if output:
                print(f"Digest saved to: {output}")
        elif args.once:
            output = pipeline.run_full_pipeline()
            if output:
                print(f"Digest saved to: {output}")
        else:
            run_scheduled()
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()

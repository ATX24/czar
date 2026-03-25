"""Digest generator for weekly trend reports."""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

import httpx
from pydantic import BaseModel, Field

from store.models import Post, Topic, TopicScore

logger = logging.getLogger(__name__)


class Theme(BaseModel):
    """A theme for the digest output."""
    rank: int
    label: str
    velocity_score: float
    novelty_score: float
    driver: Optional[str] = None
    example_posts: List[Dict[str, str]]  # [{"title": ..., "url": ..., "source": ...}]
    interpretation: str = ""
    second_order: List[str] = Field(default_factory=list)


class WeeklyDigest(BaseModel):
    """The full weekly digest output."""
    date_range: Tuple[datetime, datetime]
    generated_at: datetime
    top_themes: List[Theme]


class DigestGenerator:
    """Generates weekly digest from scored topics."""

    def __init__(
        self,
        top_n_themes: int = 10,
        example_posts_per_theme: int = 3,
        use_llm_summaries: bool = False,
        openrouter_api_key: Optional[str] = None,
        openrouter_model: str = "stepfun/step-3.5-flash:free"
    ):
        self.top_n_themes = top_n_themes
        self.example_posts_per_theme = example_posts_per_theme
        self.use_llm_summaries = use_llm_summaries and bool(openrouter_api_key)
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_model = openrouter_model

    def _get_example_posts(
        self,
        topic: Topic,
        posts: List[Post],
        scores: List[TopicScore]
    ) -> List[Dict[str, str]]:
        """Get top example posts for a topic."""
        post_id_set = set(topic.post_ids)
        topic_posts = [p for p in posts if p.id in post_id_set]

        # Sort by engagement score
        topic_posts.sort(key=lambda p: p.score, reverse=True)

        examples = []
        for post in topic_posts[:self.example_posts_per_theme]:
            # Extract title from text (first line or truncated)
            title = post.text.split("\n")[0][:100]
            if len(post.text.split("\n")[0]) > 100:
                title += "..."

            url = post.url or post.metadata.get("permalink", "")
            if not url:
                # Construct URL based on source
                if post.source == "hn":
                    url = post.metadata.get("hn_url", "")
                elif post.source == "reddit":
                    url = post.metadata.get("permalink", "")

            examples.append({
                "title": title,
                "url": url,
                "source": post.source
            })

        return examples

    def _generate_interpretation(
        self,
        theme_label: str,
        keywords: List[str],
        driver: Optional[str],
        example_posts: List[Dict[str, str]]
    ) -> str:
        """Generate 2-sentence interpretation of a theme."""
        if self.use_llm_summaries:
            return self._generate_llm_interpretation(
                theme_label, keywords, driver, example_posts
            )

        return self._generate_template_interpretation(
            theme_label, keywords, driver
        )

    def _generate_template_interpretation(
        self,
        theme_label: str,
        keywords: List[str],
        driver: Optional[str]
    ) -> str:
        """Generate interpretation using templates."""
        driver_phrases = {
            "new_paper": "driven by recent research publications",
            "new_repo": "sparked by new open-source releases",
            "benchmark": "fueled by performance breakthrough claims",
            "product_launch": "triggered by new product announcements"
        }

        driver_phrase = driver_phrases.get(driver, "gaining organic traction")

        keywords_str = ", ".join(keywords[:3])

        return (
            f"Discussion around {theme_label} is {driver_phrase}. "
            f"Key themes include {keywords_str}."
        )

    def _generate_llm_interpretation(
        self,
        theme_label: str,
        keywords: List[str],
        driver: Optional[str],
        example_posts: List[Dict[str, str]]
    ) -> str:
        """Generate interpretation using OpenRouter LLM."""
        post_titles = [p["title"] for p in example_posts[:3]]

        prompt = f"""You are a tech trend analyst. Write exactly 2 sentences interpreting this emerging topic.

Topic: {theme_label}
Keywords: {', '.join(keywords)}
Driver: {driver or 'organic growth'}
Example posts: {'; '.join(post_titles)}

Be concise, insightful, and avoid generic statements. Focus on what makes this topic significant now."""

        try:
            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.openrouter_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 150,
                    "temperature": 0.7
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"LLM interpretation failed: {e}")
            return self._generate_template_interpretation(theme_label, keywords, driver)

    def generate(
        self,
        topics: List[Topic],
        scores: List[TopicScore],
        posts: List[Post],
        date_range: Optional[Tuple[datetime, datetime]] = None
    ) -> WeeklyDigest:
        """
        Generate weekly digest from topics and scores.

        Args:
            topics: List of discovered topics
            scores: List of topic scores (pre-sorted by velocity)
            posts: All posts in the analysis window
            date_range: (start, end) of the digest period

        Returns:
            WeeklyDigest object
        """
        if date_range is None:
            end = datetime.utcnow()
            start = end - timedelta(days=7)
            date_range = (start, end)

        # Build topic lookup
        topic_by_id = {(t.run_id, t.topic_id): t for t in topics}

        themes: List[Theme] = []

        for rank, score in enumerate(scores[:self.top_n_themes], 1):
            topic_key = (score.run_id, score.topic_id)
            topic = topic_by_id.get(topic_key)

            if not topic:
                continue

            example_posts = self._get_example_posts(topic, posts, scores)

            interpretation = self._generate_interpretation(
                topic.label,
                topic.keywords,
                score.driver,
                example_posts
            )

            themes.append(Theme(
                rank=rank,
                label=topic.label,
                velocity_score=round(score.velocity, 2),
                novelty_score=round(score.novelty, 2),
                driver=score.driver,
                example_posts=example_posts,
                interpretation=interpretation,
                second_order=[]  # TODO: Add in Phase 4
            ))

        return WeeklyDigest(
            date_range=date_range,
            generated_at=datetime.utcnow(),
            top_themes=themes
        )

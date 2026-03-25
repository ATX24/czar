"""Pydantic models for trend data."""
from datetime import datetime
from typing import Any, Optional, List, Dict, Tuple

from pydantic import BaseModel, Field


class Post(BaseModel):
    """A post from any data source."""
    id: str
    source: str  # 'reddit' | 'hn' | 'x' | 'youtube' | 'github'
    collected_at: datetime
    created_at: datetime
    text: str
    url: Optional[str] = None
    score: float = 0.0  # Normalized engagement signal
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Topic(BaseModel):
    """A discovered topic from topic modeling."""
    run_id: str
    topic_id: int
    label: str
    keywords: List[str]
    post_ids: List[str]
    created_at: datetime


class TopicScore(BaseModel):
    """Scoring metrics for a topic at a point in time."""
    run_id: str
    topic_id: int
    score_date: datetime
    velocity: float = 0.0
    novelty: float = 0.0
    volume: int = 0
    inflection: bool = False
    driver: Optional[str] = None  # 'new_paper' | 'new_repo' | 'benchmark' | 'product_launch'


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

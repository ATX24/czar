"""Base collector interface."""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field


class Post(BaseModel):
    """A collected post from any source."""
    id: str
    source: str
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime
    text: str
    url: Optional[str] = None
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseCollector(ABC):
    """Abstract base class for data collectors."""

    source_name: str = "unknown"

    @abstractmethod
    def fetch(self, since: datetime) -> List[Post]:
        """
        Fetch posts since the given datetime.

        Args:
            since: Only fetch posts created after this time

        Returns:
            List of Post objects
        """
        pass

    def normalize_score(self, raw_score: float, max_score: float = 1000) -> float:
        """
        Normalize a raw engagement score to [0, 1] range.

        Uses log scaling to handle viral content without squashing
        moderate engagement.
        """
        import math
        if raw_score <= 0:
            return 0.0
        # Log scale with cap
        return min(1.0, math.log1p(raw_score) / math.log1p(max_score))

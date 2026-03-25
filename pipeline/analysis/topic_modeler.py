"""Topic modeling using BERTopic."""
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Tuple

from bertopic import BERTopic
from sentence_transformers import SentenceTransformer

from store.models import Post, Topic

logger = logging.getLogger(__name__)


class TopicModeler:
    """Topic modeling using BERTopic with sentence transformers."""

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        min_topic_size: int = 5,
        top_n_keywords: int = 5
    ):
        self.embedding_model_name = embedding_model
        self.min_topic_size = min_topic_size
        self.top_n_keywords = top_n_keywords

        # Load embedding model
        logger.info(f"Loading embedding model: {embedding_model}")
        self.embedding_model = SentenceTransformer(embedding_model)

        # Initialize BERTopic
        self.topic_model = BERTopic(
            embedding_model=self.embedding_model,
            min_topic_size=min_topic_size,
            calculate_probabilities=False,
            verbose=False
        )

        self._is_fitted = False

    def fit_transform(self, posts: List[Post]) -> Tuple[List[Topic], Dict[str, int]]:
        """
        Fit topic model on posts and return discovered topics.

        Args:
            posts: List of Post objects to model

        Returns:
            Tuple of (list of Topic objects, dict mapping post_id to topic_id)
        """
        if len(posts) < self.min_topic_size:
            logger.warning(
                f"Not enough posts ({len(posts)}) for topic modeling. "
                f"Need at least {self.min_topic_size}."
            )
            return [], {}

        # Extract texts
        texts = [post.text for post in posts]
        post_ids = [post.id for post in posts]

        logger.info(f"Fitting topic model on {len(texts)} documents")

        # Fit and transform
        topics, _ = self.topic_model.fit_transform(texts)
        self._is_fitted = True

        # Generate run ID
        run_id = str(uuid.uuid4())[:8]
        created_at = datetime.utcnow()

        # Build post_id -> topic_id mapping
        post_topic_map = dict(zip(post_ids, topics))

        # Extract topic info
        topic_info = self.topic_model.get_topic_info()

        # Build Topic objects
        result_topics: List[Topic] = []

        for _, row in topic_info.iterrows():
            topic_id = row["Topic"]

            # Skip outlier topic (-1)
            if topic_id == -1:
                continue

            # Get keywords for this topic
            topic_words = self.topic_model.get_topic(topic_id)
            if not topic_words:
                continue

            keywords = [word for word, _ in topic_words[:self.top_n_keywords]]

            # Get post IDs for this topic
            topic_post_ids = [
                pid for pid, tid in post_topic_map.items()
                if tid == topic_id
            ]

            # Generate label from top keywords
            label = " + ".join(keywords[:3])

            result_topics.append(Topic(
                run_id=run_id,
                topic_id=topic_id,
                label=label,
                keywords=keywords,
                post_ids=topic_post_ids,
                created_at=created_at
            ))

        logger.info(f"Discovered {len(result_topics)} topics")
        return result_topics, post_topic_map

    def get_topic_embeddings(self) -> Dict[int, List[float]]:
        """Get embeddings for each topic (centroid of member documents)."""
        if not self._is_fitted:
            return {}

        embeddings = {}
        topic_info = self.topic_model.get_topic_info()

        for _, row in topic_info.iterrows():
            topic_id = row["Topic"]
            if topic_id == -1:
                continue

            # Get topic embedding (if available)
            try:
                # BERTopic stores topic embeddings after fitting
                topic_words = self.topic_model.get_topic(topic_id)
                if topic_words:
                    # Embed the topic keywords
                    keywords_text = " ".join([w for w, _ in topic_words[:10]])
                    embedding = self.embedding_model.encode(keywords_text).tolist()
                    embeddings[topic_id] = embedding
            except Exception as e:
                logger.warning(f"Failed to get embedding for topic {topic_id}: {e}")

        return embeddings

    def compute_similarity(
        self,
        topic_embedding: List[float],
        other_embeddings: List[List[float]]
    ) -> List[float]:
        """Compute cosine similarity between a topic and other topics."""
        import numpy as np

        if not other_embeddings:
            return []

        topic_vec = np.array(topic_embedding)
        other_vecs = np.array(other_embeddings)

        # Normalize vectors
        topic_norm = topic_vec / (np.linalg.norm(topic_vec) + 1e-10)
        other_norms = other_vecs / (np.linalg.norm(other_vecs, axis=1, keepdims=True) + 1e-10)

        # Cosine similarity
        similarities = np.dot(other_norms, topic_norm)
        return similarities.tolist()

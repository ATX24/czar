"""Configuration for Trend Intelligence System."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
OUTPUTS_DIR = BASE_DIR / "outputs"
DB_PATH = BASE_DIR / "data" / "trends.duckdb"

# Ensure directories exist
OUTPUTS_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(exist_ok=True)

# OpenRouter API (for LLM summaries)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "stepfun/step-3.5-flash:free"

# Reddit Configuration
SUBREDDITS = [
    "MachineLearning",
    "LocalLLaMA",
    "programming",
    "artificial",
    "singularity",
    "datascience",
    "stablediffusion",
    "Python",
    "javascript",
    "webdev",
    "devops",
    "aws",
    "technology",
    "Futurology",
    "compsci",
    "learnprogramming",
    "coding",
    "startups",
    "Entrepreneur",
    "SideProject",
]

# Scoring Thresholds
VELOCITY_ZSCORE_THRESHOLD = 2.0  # Inflection detection threshold
NOVELTY_WEIGHT = 0.4  # Weight for novelty in combined score
RECENCY_WEIGHT_24H = 0.5
RECENCY_WEIGHT_7D = 0.5
INFLECTION_BONUS = 0.3

# Topic Modeling
MIN_TOPIC_SIZE = 5  # Minimum posts per topic
TOP_N_TOPICS = 10  # Number of topics for digest
TOP_N_KEYWORDS = 5  # Keywords per topic

# Time Windows
WINDOW_24H_HOURS = 24
WINDOW_72H_HOURS = 72
WINDOW_7D_HOURS = 168
BASELINE_DAYS = 30

# Collection Settings
POSTS_PER_SUBREDDIT = 100
HN_TOP_STORIES_LIMIT = 500
HN_NEW_STORIES_LIMIT = 200

# Embedding Model
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# LLM Settings
USE_LLM_SUMMARIES = bool(OPENROUTER_API_KEY)

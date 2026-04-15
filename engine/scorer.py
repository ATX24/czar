"""
Scorer
Reads data/raw/{company}/ and outputs a composite score per company across 6 dimensions.

Scoring Dimensions:
  1. Organic Growth      weight: 0.20  (GitHub stars/forks trajectory, HN mentions, Reddit velocity)
  2. Funding Velocity    weight: 0.15  (round frequency, step-up multiples, recency)
  3. Revenue Proxies     weight: 0.15  (headcount growth, job postings, LinkedIn follower growth)
  4. Product Sentiment   weight: 0.20  (HN points, Reddit score, GitHub issues vs stars)
  5. Brand Signal        weight: 0.15  (Twitter followers, engagement rate, content ratio)
  6. Founder Signal      weight: 0.15  (founder pedigree, LinkedIn presence, HN karma)

All sub-scores are normalized to [0, 1] before weighting.
Final score is on a 0–100 scale.
"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timezone


WEIGHTS = {
    "organic_growth": 0.20,
    "funding_velocity": 0.15,
    "revenue_proxies": 0.15,
    "product_sentiment": 0.20,
    "brand_signal": 0.15,
    "founder_signal": 0.15,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# Dimension scorers — each returns a float in [0, 1]
# ---------------------------------------------------------------------------

def score_organic_growth(github: dict, hn: dict, reddit: dict) -> float:
    """
    Signals: star count, 30d star gain, commit velocity, HN mention count, Reddit global mentions
    """
    sub_scores = []

    # GitHub: stars (log scale, normalized to ~1M stars = 1.0)
    stars = github.get("stars", 0) or 0
    if stars > 0:
        import math
        sub_scores.append(clamp(math.log10(stars + 1) / 6))  # log10(1M) = 6

    # GitHub: 30d star gain relative to total
    trajectory = github.get("star_trajectory_30d", {})
    gained_30d = trajectory.get("stars_gained_30d_approx", 0) or 0
    if stars > 0:
        sub_scores.append(clamp(gained_30d / max(stars, 1) * 10))  # 10%/mo growth = 1.0

    # GitHub: commit velocity (>= 50 commits/week = 1.0)
    commit_avg = (github.get("commit_velocity") or {}).get("commits_per_week_avg") or 0
    sub_scores.append(clamp(commit_avg / 50))

    # HN: mention count (500+ = 1.0)
    hn_mentions = hn.get("company_mention_count", 0) or 0
    sub_scores.append(clamp(hn_mentions / 500))

    # Reddit: global mentions (100+ = 1.0)
    reddit_mentions = reddit.get("global_mention_count", 0) or 0
    sub_scores.append(clamp(reddit_mentions / 100))

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


def score_funding_velocity(crunchbase: dict) -> float:
    """
    Signals: total raised, number of rounds, recency of last round, step-up multiples
    """
    import math

    sub_scores = []

    total = crunchbase.get("total_funding_usd", 0) or 0
    if total > 0:
        sub_scores.append(clamp(math.log10(total + 1) / 10))  # log10($10B) = 10

    num_rounds = crunchbase.get("num_funding_rounds", 0) or 0
    sub_scores.append(clamp(num_rounds / 10))  # 10+ rounds = 1.0

    # Recency of last round
    last_at = crunchbase.get("last_funding_at")
    if last_at:
        try:
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - last_dt).days
            sub_scores.append(clamp(1 - days_ago / 730))  # within 2 years = positive signal
        except Exception:
            pass

    # Tier-1 investors
    tier1 = crunchbase.get("tier1_investor_count", 0) or 0
    sub_scores.append(clamp(tier1 / 3))  # 3+ tier-1 = 1.0

    # Step-up multiples (average, capped at 5x = 1.0)
    step_ups = crunchbase.get("round_size_step_ups", []) or []
    if step_ups:
        avg_step = sum(step_ups) / len(step_ups)
        sub_scores.append(clamp(avg_step / 5))

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


def score_revenue_proxies(linkedin: dict) -> float:
    """
    Signals: headcount, follower count (LinkedIn)
    Note: without historical snapshots, headcount growth can't be directly computed.
    """
    import math

    sub_scores = []

    headcount = linkedin.get("headcount_on_linkedin", 0) or 0
    if headcount > 0:
        sub_scores.append(clamp(math.log10(headcount + 1) / 4))  # log10(10k employees) = 4

    followers = linkedin.get("follower_count", 0) or 0
    if followers > 0:
        sub_scores.append(clamp(math.log10(followers + 1) / 6))  # log10(1M followers) = 6

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


def score_product_sentiment(hn: dict, reddit: dict, github: dict) -> float:
    """
    Signals: HN top post score, Reddit top post score, GitHub open issues / stars ratio
    """
    sub_scores = []

    # HN: best post score (10k+ = 1.0)
    top_hn = hn.get("top_company_posts", []) or []
    if top_hn:
        best_hn_score = max((p.get("points") or 0) for p in top_hn)
        sub_scores.append(clamp(best_hn_score / 10000))

    # Reddit: best post score (50k+ = 1.0)
    top_reddit = reddit.get("top_posts", []) or []
    if top_reddit:
        best_reddit_score = max((p.get("score") or 0) for p in top_reddit)
        sub_scores.append(clamp(best_reddit_score / 50000))

    # GitHub: low open_issues/stars = healthy product (inverted: fewer issues per star = better)
    stars = github.get("stars", 0) or 0
    open_issues = github.get("open_issues", 0) or 0
    if stars > 0:
        ratio = open_issues / stars
        sub_scores.append(clamp(1 - ratio * 10))  # 0.1 issues/star = 0.0, 0 = 1.0

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


def score_brand_signal(twitter: dict) -> float:
    """
    Signals: follower count, engagement rate, content type diversity
    """
    import math

    sub_scores = []

    profiles = twitter.get("profiles", []) or []
    for profile in profiles:
        followers = profile.get("followers", 0) or 0
        if followers > 0:
            sub_scores.append(clamp(math.log10(followers + 1) / 7))  # log10(10M) = 7

        avg_eng = profile.get("avg_engagement_per_tweet", 0) or 0
        sub_scores.append(clamp(avg_eng / 10000))  # 10k avg engagement = 1.0

        # Content diversity: reward mix of original + link + reply
        content_ratio = profile.get("content_type_ratio", {}) or {}
        n_types = len([v for v in content_ratio.values() if v > 0])
        sub_scores.append(clamp(n_types / 4))  # 4 types = 1.0

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


def score_founder_signal(hn: dict, linkedin: dict) -> float:
    """
    Signals: HN founder mentions, LinkedIn headcount (as proxy for team quality signal)
    """
    sub_scores = []

    founder_mentions = hn.get("founder_mention_count", 0) or 0
    sub_scores.append(clamp(founder_mentions / 200))  # 200+ = 1.0

    # Placeholder: without direct founder profile data, use company follower count as signal
    followers = linkedin.get("follower_count", 0) or 0
    import math
    if followers > 0:
        sub_scores.append(clamp(math.log10(followers + 1) / 6))

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


# ---------------------------------------------------------------------------
# Main scoring entrypoint
# ---------------------------------------------------------------------------

def score_company(company_dir: Path) -> dict:
    company_name = company_dir.name

    github = load_json(company_dir / "github.json")
    hn = load_json(company_dir / "hn.json")
    reddit = load_json(company_dir / "reddit.json")
    crunchbase = load_json(company_dir / "crunchbase.json")
    linkedin = load_json(company_dir / "linkedin.json")
    twitter = load_json(company_dir / "twitter.json")

    dimension_scores = {
        "organic_growth": score_organic_growth(github, hn, reddit),
        "funding_velocity": score_funding_velocity(crunchbase),
        "revenue_proxies": score_revenue_proxies(linkedin),
        "product_sentiment": score_product_sentiment(hn, reddit, github),
        "brand_signal": score_brand_signal(twitter),
        "founder_signal": score_founder_signal(hn, linkedin),
    }

    composite = sum(WEIGHTS[k] * v for k, v in dimension_scores.items()) * 100

    return {
        "company": company_name,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "composite_score": round(composite, 2),
        "dimensions": {k: round(v * 100, 2) for k, v in dimension_scores.items()},
        "weights": WEIGHTS,
        "data_available": {
            "github": bool(github),
            "hn": bool(hn),
            "reddit": bool(reddit),
            "crunchbase": bool(crunchbase),
            "linkedin": bool(linkedin),
            "twitter": bool(twitter),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Score companies across 6 dimensions")
    parser.add_argument("--company", help="Score a specific company (by folder name). Scores all if omitted.")
    parser.add_argument("--output", default=None, help="Write results to a JSON file")
    args = parser.parse_args()

    if args.company:
        safe_name = args.company.lower().replace(" ", "_").replace("/", "_")
        company_dirs = [RAW_DIR / safe_name]
    else:
        company_dirs = [d for d in RAW_DIR.iterdir() if d.is_dir()] if RAW_DIR.exists() else []

    results = []
    for company_dir in sorted(company_dirs):
        if not company_dir.is_dir():
            print(f"  Directory not found: {company_dir}")
            continue
        result = score_company(company_dir)
        results.append(result)
        print(f"  {result['company']}: {result['composite_score']}/100")
        for dim, val in result["dimensions"].items():
            print(f"    {dim}: {val}/100")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults written to {args.output}")
    else:
        print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

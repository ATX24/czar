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
    Signals: star count, 30d star gain, commit velocity, HN story mentions + engagement, Reddit mentions
    """
    import math
    sub_scores = []

    # GitHub: stars (log scale, 1M stars = 1.0)
    stars = github.get("stars", 0) or 0
    if stars > 0:
        sub_scores.append(clamp(math.log10(stars + 1) / 6))

    # GitHub: 30d star gain (absolute, 10k gained = 1.0)
    trajectory = github.get("star_trajectory_30d", {}) or {}
    gained_30d = trajectory.get("stars_gained_30d") or 0
    if gained_30d:
        sub_scores.append(clamp(gained_30d / 10000))

    # GitHub: commit velocity 4w avg (100 commits/wk = 1.0)
    commit_avg = (github.get("commit_velocity") or {}).get("commits_per_week_4w_avg") or 0
    if commit_avg:
        sub_scores.append(clamp(commit_avg / 100))

    # HN: story mention count (500+ = 1.0)
    hn_stories = hn.get("story_mention_count", 0) or 0
    sub_scores.append(clamp(hn_stories / 500))

    # HN: total engagement score (weighted points+comments; 100k = 1.0)
    hn_eng = hn.get("total_engagement_score", 0) or 0
    sub_scores.append(clamp(hn_eng / 100000))

    # HN: Show HN posts (signal of product launches; 20+ = 1.0)
    show_hn = hn.get("show_hn_count", 0) or 0
    sub_scores.append(clamp(show_hn / 20))

    # Reddit: global mentions (100+ = 1.0)
    reddit_mentions = reddit.get("global_mention_count", 0) or 0
    if reddit_mentions:
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
    Signals: HN top story points, HN Ask HN engagement, Reddit top post score, GitHub issues/stars ratio
    """
    sub_scores = []

    # HN: best story points (2000+ = 1.0)
    top_stories = hn.get("top_stories", []) or []
    if top_stories:
        best_points = max((p.get("points") or 0) for p in top_stories)
        sub_scores.append(clamp(best_points / 2000))

    # HN: best story comment count (500+ = 1.0 — signals controversy or deep interest)
    if top_stories:
        best_comments = max((p.get("num_comments") or 0) for p in top_stories)
        sub_scores.append(clamp(best_comments / 500))

    # HN: Ask HN engagement (people actively seeking info about the product)
    ask_hn = hn.get("ask_hn_count", 0) or 0
    sub_scores.append(clamp(ask_hn / 50))

    # Reddit: best post score (50k+ = 1.0)
    top_reddit = reddit.get("top_posts", []) or []
    if top_reddit:
        best_reddit_score = max((p.get("score") or 0) for p in top_reddit)
        sub_scores.append(clamp(best_reddit_score / 50000))

    # GitHub: low open_issues/stars = healthy product (inverted)
    stars = github.get("stars", 0) or 0
    open_issues = github.get("open_issues", 0) or 0
    if stars > 0:
        ratio = open_issues / stars
        sub_scores.append(clamp(1 - ratio * 10))

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
    Signals: HN founder story mentions, founder HN karma, founder submission quality
    """
    import math
    sub_scores = []

    # Founder name mentions in HN stories (200+ = 1.0)
    founder_mentions = hn.get("founder_story_mention_count", 0) or 0
    sub_scores.append(clamp(founder_mentions / 200))

    # Founder HN profiles (karma + submission quality)
    profiles = hn.get("founder_profiles", []) or []
    for p in profiles:
        karma = p.get("karma") or 0
        if karma > 0:
            sub_scores.append(clamp(math.log10(karma + 1) / 5))  # log10(100k karma) = 5
        top_subs = p.get("top_submissions", []) or []
        if top_subs:
            best_pts = max((s.get("points") or 0) for s in top_subs)
            sub_scores.append(clamp(best_pts / 1000))

    # LinkedIn follower count as proxy (no LinkedIn data yet)
    followers = linkedin.get("follower_count", 0) or 0
    if followers > 0:
        sub_scores.append(clamp(math.log10(followers + 1) / 6))

    return sum(sub_scores) / len(sub_scores) if sub_scores else 0.0


# ---------------------------------------------------------------------------
# Main scoring entrypoint
# ---------------------------------------------------------------------------

def merge_funding_sources(crunchbase: dict, dealroom: dict, openvc: dict, wiki: dict = None) -> dict:
    """
    Merge Crunchbase, Dealroom, Wikipedia, and OpenVC into a single funding dict.
    Prefers the source with richer data; uses the highest total_funding seen.
    Priority: Crunchbase API > Wikipedia > Dealroom (for amounts — CB/Wiki are more accurate).
    """
    sources = [crunchbase, dealroom, wiki or {}]
    merged = {}

    # total_funding_usd: take the maximum non-null value across sources
    totals = [s.get("total_funding_usd") for s in sources if s.get("total_funding_usd")]
    merged["total_funding_usd"] = max(totals) if totals else None

    # valuation: Dealroom often has this, Crunchbase sometimes
    merged["last_valuation_usd"] = (
        dealroom.get("last_valuation_usd") or
        crunchbase.get("last_valuation_usd")
    )

    # num_funding_rounds: max
    rounds_counts = [s.get("num_funding_rounds") for s in sources if s.get("num_funding_rounds")]
    merged["num_funding_rounds"] = max(rounds_counts) if rounds_counts else None

    # last_funding_at: most recent
    dates = [s.get("last_funding_at") for s in sources if s.get("last_funding_at")]
    merged["last_funding_at"] = max(dates) if dates else None

    merged["last_funding_type"] = (
        crunchbase.get("last_funding_type") or dealroom.get("last_funding_type")
    )
    merged["founded_on"] = (
        crunchbase.get("founded_on") or dealroom.get("founded_on") or (wiki or {}).get("founded_on")
    )
    merged["founders"] = (
        (wiki or {}).get("founders") or []
    )

    # Merge investor lists (deduplicate by name)
    seen = set()
    investors = []
    tier1_count = 0
    for source in [crunchbase, dealroom]:
        for inv in source.get("investors", []):
            name = inv.get("name", "")
            if name and name not in seen:
                seen.add(name)
                investors.append(inv)
                if inv.get("tier") == "tier1":
                    tier1_count += 1
    # Add OpenVC investors not already seen
    for inv in openvc.get("openvc_investors", []):
        name = inv.get("name", "")
        if name and name not in seen:
            seen.add(name)
            investors.append({"name": name, "tier": "other"})

    merged["investors"]           = investors
    merged["tier1_investor_count"] = tier1_count

    # step-ups: prefer Crunchbase (more complete round history)
    merged["round_size_step_ups"] = (
        crunchbase.get("round_size_step_ups") or
        dealroom.get("round_size_step_ups") or []
    )

    # Funding rounds: union by date (prefer Crunchbase, fill in from Dealroom)
    cb_rounds = {r.get("announced_on"): r for r in crunchbase.get("funding_rounds", []) if r.get("announced_on")}
    for rd in dealroom.get("funding_rounds", []):
        k = rd.get("announced_on")
        if k and k not in cb_rounds:
            cb_rounds[k] = rd
    merged["funding_rounds"] = sorted(cb_rounds.values(), key=lambda x: x.get("announced_on") or "")

    return merged


def score_company(company_dir: Path) -> dict:
    company_name = company_dir.name

    github     = load_json(company_dir / "github.json")
    hn         = load_json(company_dir / "hn.json")
    reddit     = load_json(company_dir / "reddit.json")
    crunchbase = load_json(company_dir / "crunchbase.json")
    dealroom   = load_json(company_dir / "dealroom.json")
    openvc     = load_json(company_dir / "openvc.json")
    wiki       = load_json(company_dir / "wiki.json")
    linkedin   = load_json(company_dir / "linkedin.json")
    twitter    = load_json(company_dir / "twitter.json")

    # Merge all funding signals into one dict for the scorer
    funding = merge_funding_sources(crunchbase, dealroom, openvc, wiki)

    dimension_scores = {
        "organic_growth": score_organic_growth(github, hn, reddit),
        "funding_velocity": score_funding_velocity(funding),
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
        # Surface merged funding summary for easy inspection
        "funding_summary": {
            "total_funding_usd": funding.get("total_funding_usd"),
            "last_valuation_usd": funding.get("last_valuation_usd"),
            "num_funding_rounds": funding.get("num_funding_rounds"),
            "last_funding_at": funding.get("last_funding_at"),
            "tier1_investor_count": funding.get("tier1_investor_count", 0),
            "investors": [i["name"] for i in funding.get("investors", [])[:10]],
        },
        "data_available": {
            "github":     bool(github),
            "hn":         bool(hn),
            "reddit":     bool(reddit),
            "crunchbase": bool(crunchbase) and not crunchbase.get("error"),
            "dealroom":   bool(dealroom) and not dealroom.get("error"),
            "wikipedia":  bool(wiki) and not wiki.get("error"),
            "openvc":     bool(openvc) and not openvc.get("error"),
            "linkedin":   bool(linkedin),
            "twitter":    bool(twitter),
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

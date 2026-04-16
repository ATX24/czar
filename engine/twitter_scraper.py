"""
Twitter/X Scraper (X API v2)
Pulls: founder brand signals, follower count, engagement rate, content type ratio
Writes output to data/raw/{company_name}/twitter.json

Required env vars:
  TWITTER_BEARER_TOKEN
"""

import os
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path


BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
BASE_URL = "https://api.twitter.com/2"

HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"} if BEARER_TOKEN else {}


def get_user(username: str) -> dict:
    url = f"{BASE_URL}/users/by/username/{username}"
    params = {
        "user.fields": "public_metrics,description,created_at,verified,entities"
    }
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json().get("data", {})


def get_recent_tweets(user_id: str, max_results: int = 100) -> list:
    url = f"{BASE_URL}/users/{user_id}/tweets"
    params = {
        "max_results": max_results,
        "tweet.fields": "public_metrics,created_at,referenced_tweets,entities",
        "exclude": "retweets",
    }
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json().get("data", [])


def classify_content_type(tweet: dict) -> str:
    text = tweet.get("text", "").lower()
    refs = tweet.get("referenced_tweets", [])
    entities = tweet.get("entities", {})

    if any(r["type"] == "replied_to" for r in refs):
        return "reply"
    if entities.get("urls"):
        return "link"
    if "?" in text:
        return "question"
    return "original"


def scrape(company_name: str, founder_handles: list = None, company_handle: str = None) -> dict:
    handles = []
    if company_handle:
        handles.append(("company", company_handle))
    if founder_handles:
        for h in founder_handles:
            handles.append(("founder", h))

    profiles = []
    for handle_type, handle in handles:
        print(f"  Fetching Twitter profile for @{handle}...")
        try:
            user = get_user(handle)
            metrics = user.get("public_metrics", {})
            user_id = user.get("id")

            tweets = []
            if user_id:
                print(f"  Fetching recent tweets for @{handle}...")
                tweets = get_recent_tweets(user_id, max_results=100)

            content_counts = {}
            for tweet in tweets:
                ctype = classify_content_type(tweet)
                content_counts[ctype] = content_counts.get(ctype, 0) + 1

            total_engagement = sum(
                (t.get("public_metrics", {}).get("like_count", 0) +
                 t.get("public_metrics", {}).get("retweet_count", 0) +
                 t.get("public_metrics", {}).get("reply_count", 0))
                for t in tweets
            )
            avg_engagement = total_engagement / len(tweets) if tweets else 0

            profiles.append({
                "handle": handle,
                "type": handle_type,
                "followers": metrics.get("followers_count"),
                "following": metrics.get("following_count"),
                "tweet_count": metrics.get("tweet_count"),
                "verified": user.get("verified", False),
                "avg_engagement_per_tweet": round(avg_engagement, 2),
                "content_type_ratio": content_counts,
                "tweets_analyzed": len(tweets),
            })
        except requests.HTTPError as e:
            profiles.append({"handle": handle, "type": handle_type, "error": str(e)})

    result = {
        "company_name": company_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "profiles": profiles,
    }
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "twitter.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape Twitter/X signals for a company")
    parser.add_argument("company", help="Company name")
    parser.add_argument("--company-handle", help="Company Twitter handle")
    parser.add_argument("--founders", nargs="*", help="Founder Twitter handles")
    args = parser.parse_args()

    if not BEARER_TOKEN:
        print("WARNING: TWITTER_BEARER_TOKEN not set. Requests will fail.")

    data = scrape(args.company, args.founders, args.company_handle)
    out_file = write_output(args.company, data)
    print(f"  Output written to: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()

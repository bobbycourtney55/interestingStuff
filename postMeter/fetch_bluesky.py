"""Sample one day of Bluesky posts and attach engagement + author follower counts.

1. Replays the public Jetstream firehose from a random point inside each hour of
   the target day (UTC) and keeps the first N qualifying posts per hour:
   English, top-level (not replies), at least --min-words words.
2. Hydrates each post with like/repost/reply/quote counts via the public AppView
   (app.bsky.feed.getPosts) and the author's follower count
   (app.bsky.actor.getProfiles). No login needed.

Engagement is a snapshot at fetch time, so `age_hours` is recorded for use as a control.

Usage:
    python fetch_bluesky.py --date 2026-10-06 --per-hour 100 -o bsky_posts.csv
"""
import argparse
import csv
import datetime as dt
import json
import os
import random
import re
import ssl
import sys
import time

import requests
from websockets.sync.client import connect

JETSTREAM = "wss://jetstream2.us-east.bsky.network/subscribe"
APPVIEW = "https://public.api.bsky.app/xrpc"
WORD_RE = re.compile(r"[a-zA-Z]+")
COUNTS = {"likeCount": "likes", "repostCount": "reposts", "replyCount": "replies", "quoteCount": "quotes"}


def ssl_context():
    # Honour a custom CA bundle if the environment sets one (e.g. behind a proxy).
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=cafile)


def embed_kind(record):
    embed = record.get("embed") or {}
    t = embed.get("$type", "")
    if "recordWithMedia" in t:
        return "quote+media"
    if "images" in t or "video" in t:
        return "media"
    if "external" in t:
        return "link"
    if "record" in t:
        return "quote"
    return ""


def sample_hour(hour_start, per_hour, min_words, max_seconds=120):
    """Collect up to per_hour qualifying posts starting at a random second in the hour."""
    start = hour_start + dt.timedelta(seconds=random.randrange(3600 - 300))
    cursor = int(start.timestamp() * 1_000_000)
    hour_end_us = int((hour_start + dt.timedelta(hours=1)).timestamp() * 1_000_000)
    url = f"{JETSTREAM}?wantedCollections=app.bsky.feed.post&cursor={cursor}"
    posts, deadline, first = [], time.time() + max_seconds, True
    with connect(url, ssl=ssl_context(), max_size=2**22, open_timeout=30) as ws:
        while len(posts) < per_hour and time.time() < deadline:
            ev = json.loads(ws.recv(timeout=30))
            if first and ev.get("time_us", 0) > cursor + 600_000_000:
                # A cursor older than retention replays from the oldest event kept instead.
                raise RuntimeError(f"Jetstream no longer retains {start.isoformat()}")
            first = False
            if ev.get("time_us", 0) >= hour_end_us:
                break
            c = ev.get("commit") or {}
            if ev.get("kind") != "commit" or c.get("operation") != "create":
                continue
            rec = c.get("record") or {}
            text = rec.get("text", "")
            if rec.get("reply") or "en" not in (rec.get("langs") or []):
                continue
            if len(WORD_RE.findall(text)) < min_words:
                continue
            posts.append({
                "uri": f"at://{ev['did']}/app.bsky.feed.post/{c['rkey']}",
                "did": ev["did"],
                "created_at": rec.get("createdAt", ""),
                "embed": embed_kind(rec),
                "text": text,
            })
    return posts


def get_json(endpoint, params, retries=4):
    for attempt in range(retries):
        r = requests.get(f"{APPVIEW}/{endpoint}", params=params, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def hydrate(posts):
    now = dt.datetime.now(dt.timezone.utc)
    by_uri = {p["uri"]: p for p in posts}
    for batch in chunks(list(by_uri), 25):
        for pv in get_json("app.bsky.feed.getPosts", [("uris", u) for u in batch])["posts"]:
            p = by_uri[pv["uri"]]
            for api_name, col in COUNTS.items():
                p[col] = pv.get(api_name, 0)
            p["handle"] = pv["author"]["handle"]
    dids = sorted({p["did"] for p in posts})
    followers = {}
    for batch in chunks(dids, 25):
        for prof in get_json("app.bsky.actor.getProfiles", [("actors", d) for d in batch])["profiles"]:
            followers[prof["did"]] = (prof.get("followersCount", 0), prof.get("postsCount", 0))
    kept = []
    for p in posts:
        # Posts deleted since, or authors who opt out of logged-out visibility, drop out here.
        if "likes" not in p or p["did"] not in followers:
            continue
        p["followers"], p["author_posts"] = followers[p["did"]]
        try:
            created = dt.datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
            p["age_hours"] = round((now - created).total_seconds() / 3600, 2)
        except ValueError:
            p["age_hours"] = ""
        kept.append(p)
    return kept


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date()
    ap.add_argument("--date", default=str(yesterday), help="UTC day to sample (default: yesterday)")
    ap.add_argument("--per-hour", type=int, default=100)
    ap.add_argument("--min-words", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-o", "--output", default="bsky_posts.csv")
    args = ap.parse_args()
    random.seed(args.seed)

    day = dt.datetime.fromisoformat(args.date).replace(tzinfo=dt.timezone.utc)
    posts = []
    for h in range(24):
        got = sample_hour(day + dt.timedelta(hours=h), args.per_hour, args.min_words)
        print(f"{h:02d}:00 UTC  {len(got)} posts", file=sys.stderr)
        posts += got
    posts = hydrate(posts)
    print(f"{len(posts)} posts after hydration", file=sys.stderr)

    fields = ["uri", "handle", "did", "created_at", "age_hours", "embed", "followers", "author_posts",
              "likes", "reposts", "replies", "quotes", "text"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(posts)


if __name__ == "__main__":
    main()

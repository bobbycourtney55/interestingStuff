"""Find popular Bluesky posts from a 24h window and pair them with the same authors' ordinary posts.

1. Replays repost events from Jetstream, from the window start until now, and
   tallies reposts per subject post created inside the window. A post's creation
   time is read from its record key (a TID timestamp), so no lookups are needed.
2. Hydrates the most-reposted candidates and keeps English, top-level posts of
   at least --min-words words with at least --threshold reposts.
3. For each popular author, pulls their recent feed and keeps up to
   --controls-per-author of their other original posts below the threshold,
   nearest in time to the popular post, as within-author controls.

Output CSV has a `group` column: "popular" or "control".

Usage:
    python fetch_popular.py --start 2026-10-06T08:00 --threshold 25 -o bsky_pairs.csv
"""
import argparse
import csv
import datetime as dt
import json
import os
import random
import sys
import time
from collections import Counter

from websockets.sync.client import connect

from fetch_bluesky import JETSTREAM, WORD_RE, chunks, embed_kind, get_json, ssl_context

B32 = "234567abcdefghijklmnopqrstuvwxyz"
FIELDS = ["group", "uri", "handle", "did", "created_at", "age_hours", "embed", "followers",
          "likes", "reposts", "replies", "quotes", "text"]


def tid_time_us(rkey):
    """Microsecond timestamp encoded in an atproto TID record key, or None."""
    if len(rkey) != 13:
        return None
    n = 0
    for ch in rkey:
        i = B32.find(ch)
        if i < 0:
            return None
        n = n * 32 + i
    return n >> 10


def tally_reposts(start_us, end_us, stop_us):
    """Count reposts (up to stop_us) of posts created in [start_us, end_us)."""
    counts = Counter()
    url = f"{JETSTREAM}?wantedCollections=app.bsky.feed.repost&cursor={start_us}"
    n, last_report = 0, time.time()
    with connect(url, ssl=ssl_context(), max_size=2**22, open_timeout=30) as ws:
        while True:
            ev = json.loads(ws.recv(timeout=60))
            if ev.get("time_us", 0) >= stop_us:
                break
            c = ev.get("commit") or {}
            if ev.get("kind") != "commit" or c.get("operation") != "create":
                continue
            uri = ((c.get("record") or {}).get("subject") or {}).get("uri", "")
            if "/app.bsky.feed.post/" not in uri:
                continue
            created = tid_time_us(uri.rsplit("/", 1)[1])
            if created is not None and start_us <= created < end_us:
                counts[uri] += 1
            n += 1
            if time.time() - last_report > 60:
                at = dt.datetime.fromtimestamp(ev["time_us"] / 1e6, dt.timezone.utc)
                print(f"  {n:,} reposts read, stream at {at:%m-%d %H:%M} UTC", file=sys.stderr)
                last_report = time.time()
    print(f"{n:,} reposts read; {len(counts):,} window posts reposted", file=sys.stderr)
    return counts


def post_row(pv, group, now):
    rec = pv.get("record") or {}
    created = rec.get("createdAt", "")
    try:
        age = round((now - dt.datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 3600, 2)
    except ValueError:
        age = ""
    return {
        "group": group, "uri": pv["uri"], "handle": pv["author"]["handle"], "did": pv["author"]["did"],
        "created_at": created, "age_hours": age, "embed": embed_kind(rec),
        "likes": pv.get("likeCount", 0), "reposts": pv.get("repostCount", 0),
        "replies": pv.get("replyCount", 0), "quotes": pv.get("quoteCount", 0), "text": rec.get("text", ""),
    }


def eligible(pv, min_words):
    rec = pv.get("record") or {}
    return (not rec.get("reply") and "en" in (rec.get("langs") or [])
            and len(WORD_RE.findall(rec.get("text", ""))) >= min_words)


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="UTC start of the 24h window, e.g. 2026-10-06T08:00")
    ap.add_argument("--threshold", type=int, default=25, help="minimum reposts to count as popular")
    ap.add_argument("--min-words", type=int, default=5)
    ap.add_argument("--max-popular", type=int, default=800, help="random cap on popular posts kept")
    ap.add_argument("--controls-per-author", type=int, default=5)
    ap.add_argument("--control-days", type=float, default=30, help="max days between control and popular post")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-o", "--output", default="bsky_pairs.csv")
    args = ap.parse_args()
    random.seed(args.seed)

    start = dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    now = dt.datetime.now(dt.timezone.utc)

    # Cache the tally, the slow step, so later steps can be rerun cheaply.
    tally_path = args.output + ".tally.json"
    if os.path.exists(tally_path):
        with open(tally_path, encoding="utf-8") as f:
            counts = Counter(json.load(f))
    else:
        counts = tally_reposts(int(start.timestamp() * 1e6), int(end.timestamp() * 1e6), int(now.timestamp() * 1e6))
        # Keep only plausible candidates; the stream can miss a few reposts, so allow some slack.
        counts = Counter({u: c for u, c in counts.items() if c >= args.threshold * 0.8})
        with open(tally_path, "w", encoding="utf-8") as f:
            json.dump(counts, f)
    print(f"{len(counts):,} candidates with >= {args.threshold * 0.8:.0f} streamed reposts", file=sys.stderr)

    popular = []
    for batch in chunks([u for u, _ in counts.most_common()], 25):
        for pv in get_json("app.bsky.feed.getPosts", [("uris", u) for u in batch])["posts"]:
            if pv.get("repostCount", 0) >= args.threshold and eligible(pv, args.min_words):
                popular.append(post_row(pv, "popular", now))
    print(f"{len(popular):,} popular posts (English, top-level, >= {args.threshold} reposts)", file=sys.stderr)
    if len(popular) > args.max_popular:
        popular = random.sample(popular, args.max_popular)

    popular_uris = {p["uri"] for p in popular}
    controls = []
    by_author = {}
    for p in popular:
        by_author.setdefault(p["did"], []).append(p)
    for i, (did, posts) in enumerate(by_author.items()):
        try:
            feed = get_json("app.bsky.feed.getAuthorFeed",
                            {"actor": did, "filter": "posts_no_replies", "limit": 100})["feed"]
        except Exception as e:  # deleted/suspended/opted-out accounts
            print(f"  skip {did}: {e}", file=sys.stderr)
            continue
        anchor = sum(parse_time(p["created_at"]) for p in posts) / len(posts)
        cands = []
        for item in feed:
            pv = item["post"]
            if item.get("reason") or pv["author"]["did"] != did or pv["uri"] in popular_uris:
                continue
            if pv.get("repostCount", 0) >= args.threshold or not eligible(pv, args.min_words):
                continue
            row = post_row(pv, "control", now)
            try:
                t = parse_time(row["created_at"])
            except ValueError:
                continue
            # Controls need comparable exposure time: posted no later than the window end.
            if t <= end.timestamp() and abs(t - anchor) <= args.control_days * 86400:
                cands.append((abs(t - anchor), row))
        cands.sort(key=lambda x: x[0])
        controls += [row for _, row in cands[:args.controls_per_author]]
        if (i + 1) % 100 == 0:
            print(f"  controls fetched for {i + 1}/{len(by_author)} authors", file=sys.stderr)

    rows = popular + controls
    followers = {}
    for batch in chunks(sorted({r["did"] for r in rows}), 25):
        for prof in get_json("app.bsky.actor.getProfiles", [("actors", d) for d in batch])["profiles"]:
            followers[prof["did"]] = prof.get("followersCount", 0)
    for r in rows:
        r["followers"] = followers.get(r["did"], "")

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    n_auth = len({r["did"] for r in controls})
    print(f"wrote {len(popular)} popular + {len(controls)} control posts ({n_auth} authors with controls)",
          file=sys.stderr)


if __name__ == "__main__":
    main()

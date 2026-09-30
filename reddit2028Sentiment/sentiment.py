"""Share of Reddit posts about potential 2028 Democratic primary candidates that
talk about each candidate positively vs. negatively.

Three steps, each writing a file the next one reads:

  python sentiment.py fetch     # Reddit search API  -> data/posts.jsonl
  python sentiment.py classify  # Claude stance calls -> data/stances.jsonl
  python sentiment.py report    # tallies            -> data/summary.csv (+ printed table)

`fetch` needs a Reddit "script" app (https://www.reddit.com/prefs/apps):
REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET. `classify` needs Anthropic API
credentials (ANTHROPIC_API_KEY or an `ant auth login` profile).
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
import requests

DATA = Path(__file__).parent / "data"
POSTS = DATA / "posts.jsonl"
STANCES = DATA / "stances.jsonl"
SUMMARY = DATA / "summary.csv"

USER_AGENT = "script:interestingStuff-2028-sentiment:v1.0 (research)"
MODEL = "claude-opus-5-5"

# name -> (Reddit search queries, regex a post must match to count as a mention).
# Last names alone are ambiguous for Harris ("Harris County", other Harrises) and
# AOC (Age of Conan, "AoC" = Advent of Code), so those need the fuller form or
# exact uppercase. Claude also marks a match "not_about" when it isn't the politician.
CANDIDATES = {
    "Gavin Newsom": (['"Newsom"'], r"\bNewsom\b"),
    "Alexandria Ocasio-Cortez": (['"AOC"', '"Ocasio-Cortez"'], r"\bAOC\b|Ocasio[- ]Cortez"),
    "Pete Buttigieg": (['"Buttigieg"', '"Mayor Pete"'], r"\bButtigieg\b|\bMayor Pete\b"),
    "Kamala Harris": (['"Kamala"', '"Kamala Harris"'], r"\bKamala\b|\b(?:VP|Vice President|President) Harris\b"),
    "JB Pritzker": (['"Pritzker"'], r"\bPritzker\b"),
    "Jon Ossoff": (['"Ossoff"'], r"\bOssoff\b"),
    "Ro Khanna": (['"Ro Khanna"', '"Khanna"'], r"\bKhanna\b"),
}
PATTERNS = {
    name: re.compile(rx, 0 if name == "Alexandria Ocasio-Cortez" else re.IGNORECASE)
    for name, (_, rx) in CANDIDATES.items()
}


def mentioned(post):
    text = f"{post['title']}\n{post['selftext']}"
    return [name for name, rx in PATTERNS.items() if rx.search(text)]


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- fetch


def reddit_token():
    cid, secret = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (create a 'script' app at reddit.com/prefs/apps).")
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search(session, query, sort, window):
    """Yield posts for one query. Reddit stops paginating after roughly 250-1000
    results per query+sort, so fetch() runs several sorts and merges by id."""
    after = None
    while True:
        params = {"q": query, "sort": sort, "t": window, "type": "link", "limit": 100, "raw_json": 1}
        if after:
            params["after"] = after
        r = session.get("https://oauth.reddit.com/search", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(int(float(r.headers.get("x-ratelimit-reset", 60))) + 1)
            continue
        r.raise_for_status()
        if float(r.headers.get("x-ratelimit-remaining", 10)) < 2:
            time.sleep(int(float(r.headers.get("x-ratelimit-reset", 60))) + 1)
        listing = r.json()["data"]
        for child in listing["children"]:
            yield child["data"]
        after = listing.get("after")
        if not after:
            return


def fetch(args):
    DATA.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Authorization": f"bearer {reddit_token()}"})
    cutoff = time.time() - args.days * 86400

    posts = {p["id"]: p for p in read_jsonl(POSTS)}
    for name, (queries, _) in CANDIDATES.items():
        before = len(posts)
        for query in queries:
            for sort in ("new", "relevance", "top", "comments"):
                for d in search(session, query, sort, args.window):
                    if d["created_utc"] < cutoff or d["id"] in posts:
                        continue
                    posts[d["id"]] = {
                        "id": d["id"],
                        "subreddit": d["subreddit"],
                        "created_utc": d["created_utc"],
                        "score": d["score"],
                        "num_comments": d["num_comments"],
                        "title": d["title"],
                        "selftext": d.get("selftext", ""),
                        "url": d.get("url", ""),
                        "permalink": "https://www.reddit.com" + d["permalink"],
                    }
        print(f"{name}: +{len(posts) - before} posts")

    kept = [p for p in posts.values() if mentioned(p)]
    with POSTS.open("w") as f:
        for p in kept:
            f.write(json.dumps(p) + "\n")
    print(f"Wrote {len(kept)} posts that name at least one candidate to {POSTS}")


# ---------------------------------------------------------------- classify

SYSTEM = """You label the stance a Reddit post takes toward specific US politicians.

For each politician listed, decide how the post (its author's framing, title and body) portrays that person:
- positive: praises, defends, supports, is enthusiastic about, or frames them favorably (including favorable news framing).
- negative: criticizes, mocks, attacks, expresses opposition or disappointment, or frames them unfavorably.
- neutral: mentions them without a clear favorable or unfavorable slant, is a balanced/straight news report, or the slant is mixed evenly.
- not_about: the name match refers to someone or something else (e.g. Harris County, "AoC" = Advent of Code).

Judge the stance toward each person separately: a post can be positive about one and negative about another.
Sarcasm counts by its intended meaning. Do not infer stance from the subreddit alone."""

STANCE_VALUES = ["positive", "negative", "neutral", "not_about"]


def schema(names):
    return {
        "type": "object",
        "properties": {
            "stances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "string", "enum": names},
                        "stance": {"type": "string", "enum": STANCE_VALUES},
                    },
                    "required": ["candidate", "stance"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["stances"],
        "additionalProperties": False,
    }


def label_stances(client, system, prompt, names):
    """Ask Claude for each name's stance. Returns {name: stance}, or None if the
    API kept failing (the caller leaves the item for a later rerun)."""
    for attempt in range(5):
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema(names)}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError):
            time.sleep(2 ** attempt * 5)
    else:
        return None
    if response.stop_reason == "refusal":
        return {name: "refused" for name in names}
    text = next(b.text for b in response.content if b.type == "text")
    got = {s["candidate"]: s["stance"] for s in json.loads(text)["stances"]}
    return {name: got.get(name, "neutral") for name in names}


def classify_post(client, post, names):
    body = post["selftext"][:6000]
    prompt = (
        f"Subreddit: r/{post['subreddit']}\nTitle: {post['title']}\n"
        f"Link: {post['url']}\nBody:\n{body or '(no body text)'}\n\n"
        f"Label the stance toward each of: {', '.join(names)}."
    )
    return label_stances(client, SYSTEM, prompt, names)


def classify(args):
    client = anthropic.Anthropic()
    done = {row["id"] for row in read_jsonl(STANCES)}
    todo = [p for p in read_jsonl(POSTS) if p["id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Classifying {len(todo)} posts ({len(done)} already done)")

    with STANCES.open("a") as out, ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(classify_post, client, p, mentioned(p)): p for p in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            post, stances = futures[fut], fut.result()
            if stances is None:
                print(f"  gave up on {post['id']} after retries; rerun classify to retry")
                continue
            out.write(json.dumps({"id": post["id"], "subreddit": post["subreddit"], "stances": stances}) + "\n")
            out.flush()
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}")


# ---------------------------------------------------------------- report


def report(args):
    counts = defaultdict(Counter)
    for row in read_jsonl(STANCES):
        for name, stance in row["stances"].items():
            counts[name][stance] += 1

    header = ["candidate", "posts", "positive", "negative", "neutral",
              "pct_positive", "pct_negative", "pct_neutral", "pos_share_of_polar", "excluded_not_about_or_refused"]
    rows = []
    for name in CANDIDATES:
        c = counts[name]
        n = c["positive"] + c["negative"] + c["neutral"]
        polar = c["positive"] + c["negative"]
        pct = lambda k: round(100 * c[k] / n, 1) if n else None
        rows.append([
            name, n, c["positive"], c["negative"], c["neutral"],
            pct("positive"), pct("negative"), pct("neutral"),
            round(100 * c["positive"] / polar, 1) if polar else None,
            c["not_about"] + c["refused"],
        ])
    rows.sort(key=lambda r: -(r[8] or 0))

    DATA.mkdir(exist_ok=True)
    with SUMMARY.open("w", newline="") as f:
        csv.writer(f).writerows([header, *rows])

    print(f"{'Candidate':26}{'Posts':>7}{'%Pos':>7}{'%Neg':>7}{'%Neu':>7}{'Pos/(Pos+Neg)':>15}")
    for r in rows:
        fmt = lambda v: "-" if v is None else f"{v}"
        print(f"{r[0]:26}{r[1]:>7}{fmt(r[5]):>7}{fmt(r[6]):>7}{fmt(r[7]):>7}{fmt(r[8]):>15}")
    print(f"\nWrote {SUMMARY}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="collect posts from the Reddit search API")
    f.add_argument("--days", type=int, default=365, help="only keep posts newer than this (default 365)")
    f.add_argument("--window", default="year", choices=["day", "week", "month", "year", "all"],
                   help="Reddit search time filter (default year)")
    c = sub.add_parser("classify", help="label each post's stance per candidate with Claude")
    c.add_argument("--workers", type=int, default=8)
    c.add_argument("--limit", type=int, default=0, help="classify at most N new posts (0 = all)")
    sub.add_parser("report", help="tabulate positive/negative shares")
    args = parser.parse_args()
    {"fetch": fetch, "classify": classify, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()

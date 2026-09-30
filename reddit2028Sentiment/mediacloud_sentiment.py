"""Percent of US national news articles in Media Cloud that portray each
potential 2028 Democratic primary candidate positively, by month.

  python mediacloud_sentiment.py fetch     # Media Cloud sample -> data/mc_stories.jsonl
  python mediacloud_sentiment.py classify  # Claude stance calls -> data/mc_stances.jsonl
  python mediacloud_sentiment.py report    # data/mc_monthly.csv + data/mc_pct_positive.png

`fetch` needs a Media Cloud API key (search.mediacloud.org -> your profile):
MEDIACLOUD_API_KEY. `classify` needs Anthropic API credentials.

Only articles whose headline names the candidate are used: Media Cloud's free
tier returns headlines but not article text, and a headline that names someone
is what carries a stance toward them. Every such headline in each month is
fetched (up to --max-per-month). The free tier allows 2 requests a minute, so
a full fetch takes about 45 minutes.
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from sentiment import DATA, label_stances, read_jsonl

STORIES = DATA / "mc_stories.jsonl"
MC_STANCES = DATA / "mc_stances.jsonl"
MONTHLY = DATA / "mc_monthly.csv"
CHART = DATA / "mc_pct_positive.png"

US_NATIONAL = 34412234  # Media Cloud "United States - National" collection
MAX_TEXT = 12000  # characters of article text sent to Claude, when the account can fetch text

# Headline must name the candidate. "Harris" alone also hits other Harrises, so a
# Harris headline counts only when the article text says "Kamala" too.
QUERIES = {
    "Gavin Newsom": "article_title:Newsom",
    "Alexandria Ocasio-Cortez": 'article_title:"Ocasio-Cortez" OR article_title:AOC',
    "Pete Buttigieg": "article_title:Buttigieg",
    "Kamala Harris": "article_title:Kamala OR (article_title:Harris AND Kamala)",
    "JB Pritzker": "article_title:Pritzker",
    "Jon Ossoff": "article_title:Ossoff",
    "Ro Khanna": "article_title:Khanna",
}


def months(year, through):
    m = dt.date(year, 1, 1)
    while m <= through:
        nxt = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        yield m, min(nxt - dt.timedelta(days=1), through)
        m = nxt


# ---------------------------------------------------------------- fetch


def fetch(args):
    import mediacloud.api

    key = os.environ.get("MEDIACLOUD_API_KEY")
    if not key:
        sys.exit("Set MEDIACLOUD_API_KEY (from your profile at search.mediacloud.org).")
    mc = mediacloud.api.SearchApi(key)
    pause = 60 / mc.RATE_LIMIT_PER_MINUTE

    def call(fn, *a, **kw):
        for attempt in range(6):
            try:
                time.sleep(pause)
                return fn(*a, **kw)
            except Exception as e:  # the client raises plain exceptions for HTTP and network errors
                print(f"  retrying after error: {str(e)[:120]}")
                time.sleep(min(2 ** attempt * 30, 300))
        raise RuntimeError("Media Cloud kept failing; rerun fetch to resume")

    def month_stories(query, start, end):
        """Every matching story in the month, paging 1,000 at a time, stopping at --max-per-month."""
        stories, token = [], None
        while True:
            page, token = call(mc.story_list, query, start, end, collection_ids=[US_NATIONAL],
                               expanded=args.full_text, page_size=1000, pagination_token=token)
            stories += page
            if not token or len(stories) >= args.max_per_month:
                return stories[: args.max_per_month], bool(token)

    DATA.mkdir(exist_ok=True)
    have = {(r["candidate"], r["month"]) for r in read_jsonl(STORIES)}
    today = dt.date.today()
    with STORIES.open("a") as out:
        for name, query in QUERIES.items():
            for start, end in months(args.year, today):
                month = start.strftime("%Y-%m")
                if (name, month) in have:
                    continue
                stories, sampled = month_stories(query, start, end)
                seen, kept = set(), []
                for s in stories:
                    dup = (s.get("media_name"), (s.get("title") or "").strip().lower())
                    if s.get("language", "en") == "en" and dup not in seen:
                        seen.add(dup)
                        kept.append(s)
                for s in kept:
                    out.write(json_line({
                        "key": f"{name}|{s['id']}",
                        "candidate": name,
                        "month": month,
                        "sampled": sampled,
                        "id": s["id"],
                        "title": s.get("title", ""),
                        "url": s.get("url", ""),
                        "media_name": s.get("media_name", ""),
                        "publish_date": str(s.get("publish_date") or ""),
                        "text": (s.get("text") or "")[:MAX_TEXT],
                    }))
                if not kept:  # record the month so a rerun doesn't query it again
                    out.write(json_line({"key": f"{name}|none|{month}", "candidate": name, "month": month,
                                         "sampled": False, "empty": True}))
                out.flush()
                how = f"first {len(kept)} (hit --max-per-month)" if sampled else f"all {len(kept)}"
                print(f"{name} {month}: {how}", flush=True)


def json_line(obj):
    return json.dumps(obj) + "\n"


# ---------------------------------------------------------------- classify

SYSTEM = """You label how a news article portrays a specific US politician.

- positive: the article on balance portrays them favorably: praise, successes, endorsements, favorable framing or quotes left unrebutted.
- negative: the article on balance portrays them unfavorably: criticism, scandal, failures, attacks, unfavorable framing.
- neutral: straight or balanced reporting, a passing mention, or favorable and unfavorable content in roughly equal measure.
- not_about: the name refers to someone or something else (e.g. a different person named Harris).

Judge the portrayal of this person only, not of their party or of other people in the story.
A negative event reported about them (an indictment, a lost vote, a poll slump) counts as negative even if the tone is dry.
Often you will see only the headline; judge the portrayal the headline conveys."""


def classify_story(client, story):
    name = story["candidate"]
    prompt = (
        f"Outlet: {story['media_name']}\nDate: {story['publish_date']}\n"
        f"Headline: {story['title']}\nURL: {story['url']}\n"
        f"Article text:\n{story['text'] or '(text unavailable; judge from the headline)'}\n\n"
        f"How does this article portray {name}?"
    )
    stances = label_stances(client, SYSTEM, prompt, [name])
    return None if stances is None else stances[name]


def classify(args):
    client = anthropic.Anthropic()
    done = {r["key"] for r in read_jsonl(MC_STANCES)}
    todo = [s for s in read_jsonl(STORIES) if s["key"] not in done and not s.get("empty")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Classifying {len(todo)} articles ({len(done)} already done)")

    with MC_STANCES.open("a") as out, ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(classify_story, client, s): s for s in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            story, stance = futures[fut], fut.result()
            if stance is None:
                print(f"  gave up on {story['key']} after retries; rerun classify to retry")
                continue
            out.write(json_line({"key": story["key"], "candidate": story["candidate"],
                                 "month": story["month"], "media_name": story["media_name"], "stance": stance}))
            out.flush()
            if i % 200 == 0:
                print(f"  {i}/{len(todo)}")


# ---------------------------------------------------------------- report

MIN_N = 30  # months with fewer classified articles are drawn hollow: too noisy to read much into


def report(args):
    counts = defaultdict(Counter)
    sampled = {}
    for s in read_jsonl(STORIES):
        sampled[(s["candidate"], s["month"])] = s["sampled"]
    for r in read_jsonl(MC_STANCES):
        counts[(r["candidate"], r["month"])][r["stance"]] += 1

    rows = []
    for (name, month), c in sorted(counts.items()):
        n = c["positive"] + c["negative"] + c["neutral"]
        if not n:
            continue
        rows.append({
            "candidate": name, "month": month, "coverage": "capped" if sampled.get((name, month)) else "all headlines",
            "classified": n, "positive": c["positive"], "negative": c["negative"], "neutral": c["neutral"],
            "pct_positive": round(100 * c["positive"] / n, 1),
            "pct_negative": round(100 * c["negative"] / n, 1),
            "excluded_not_about_or_refused": c["not_about"] + c["refused"],
        })
    with MONTHLY.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {MONTHLY}")
    plot(rows, args.year)
    print(f"Wrote {CHART}")


def plot(rows, year):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink2, muted, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
    accent, context = "#2a78d6", "#d3d1c9"

    all_months = sorted({r["month"] for r in rows})
    x = {m: i for i, m in enumerate(all_months)}
    labels = [dt.date.fromisoformat(m + "-01").strftime("%b") for m in all_months]
    series = defaultdict(list)
    for r in rows:
        series[r["candidate"]].append(r)
    names = [n for n in QUERIES if n in series]
    # Panels ordered by average % positive, highest first, so the grid reads as a ranking.
    names.sort(key=lambda n: -sum(r["pct_positive"] for r in series[n]) / len(series[n]))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(2, 4, figsize=(14, 6.6), sharex=True, sharey=True, facecolor=surface)
    for ax in axes.flat:
        ax.set_facecolor(surface)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(grid)
        ax.tick_params(colors=muted, length=0)
        ax.grid(axis="y", color=grid, linewidth=1)
        ax.set_axisbelow(True)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
        ax.set_xticks(range(len(all_months)))
        ax.set_xticklabels(labels)

    for ax, name in zip(axes.flat, names):
        for other in names:
            if other != name:
                pts = series[other]
                ax.plot([x[r["month"]] for r in pts], [r["pct_positive"] for r in pts],
                        color=context, linewidth=1, solid_capstyle="round", zorder=1)
        pts = series[name]
        xs, ys = [x[r["month"]] for r in pts], [r["pct_positive"] for r in pts]
        ax.plot(xs, ys, color=accent, linewidth=2, solid_joinstyle="round", solid_capstyle="round", zorder=2)
        for r, xi, yi in zip(pts, xs, ys):
            solid = r["classified"] >= MIN_N
            ax.plot(xi, yi, "o", markersize=6, markeredgewidth=2 if solid else 1.5,
                    markerfacecolor=accent if solid else surface,
                    markeredgecolor=surface if solid else accent, zorder=3)
        last = pts[-1]
        ax.set_title(name, loc="left", color=ink, fontsize=11, fontweight="bold", pad=18)
        ax.text(0, 1.02, f"{last['pct_positive']:.0f}% positive in {labels[x[last['month']]]}"
                         f"  ·  n={last['classified']}",
                transform=ax.transAxes, color=ink2, fontsize=9)

    key = axes.flat[len(names)] if len(names) < 8 else None
    for ax in list(axes.flat)[len(names):]:
        ax.axis("off")
    if key is not None:
        key.plot([0.05, 0.2], [0.78, 0.78], color=accent, linewidth=2, transform=key.transAxes)
        key.text(0.25, 0.78, "Candidate in panel title", va="center", color=ink2, transform=key.transAxes)
        key.plot([0.05, 0.2], [0.64, 0.64], color=context, linewidth=1, transform=key.transAxes)
        key.text(0.25, 0.64, "Other candidates", va="center", color=ink2, transform=key.transAxes)
        key.plot(0.125, 0.5, "o", markersize=6, markerfacecolor=surface, markeredgecolor=accent,
                 markeredgewidth=1.5, transform=key.transAxes)
        key.text(0.25, 0.5, f"Fewer than {MIN_N} articles classified", va="center", color=ink2,
                 transform=key.transAxes)
        key.text(0.05, 0.28, "% positive = positive ÷ (positive +\nnegative + neutral) articles",
                 va="center", color=muted, fontsize=9, transform=key.transAxes)

    fig.suptitle(f"Share of US national news articles portraying each candidate positively, {year}",
                 x=0.012, ha="left", color=ink, fontsize=14, fontweight="bold")
    fig.text(0.012, 0.915, "Headlines naming the candidate in Media Cloud's 'United States - National' collection; "
                           "stance labeled by Claude", color=ink2, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.9), h_pad=2.5)
    fig.savefig(CHART, dpi=160, facecolor=surface)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="sample articles from Media Cloud")
    f.add_argument("--max-per-month", type=int, default=3000,
                   help="stop paging a candidate-month after this many articles (default 3000)")
    f.add_argument("--full-text", action="store_true",
                   help="also fetch article text (needs a Media Cloud account allowed 'expanded' stories)")
    c = sub.add_parser("classify", help="label each article's portrayal of its candidate with Claude")
    c.add_argument("--workers", type=int, default=8)
    c.add_argument("--limit", type=int, default=0, help="classify at most N new articles (0 = all)")
    sub.add_parser("report", help="monthly table and chart")
    args = parser.parse_args()
    {"fetch": fetch, "classify": classify, "report": report}[args.cmd](args)


if __name__ == "__main__":
    main()

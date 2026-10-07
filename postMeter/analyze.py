"""Correlate rhythm features with engagement, with and without controls.

Reads the CSV from fetch_bluesky.py, scores each post with score_meter.score, and
for each outcome (likes, reposts) reports:
  - raw Spearman rho between each feature and the outcome
  - partial Spearman rho controlling for log followers, syllable count, post age
    and embed type (rank-transform everything, regress out controls, correlate residuals)
  - an approximate 95% CI from the Fisher z-transform

Usage:
    python analyze.py bsky_posts.csv [-o scored.csv]
"""
import argparse
import csv
import math

import numpy as np

from score_meter import score

FEATURES = ["alternation", "clash_rate", "lapse_count", "beat_regularity", "final_stressed", "fit_duple", "fit_triple",
            "segment_balance", "end_rhyme", "fit_iambic", "fit_trochaic", "fit_anapestic",
            "fit_dactylic", "pentameter_line"]
OUTCOMES = ["likes", "reposts"]
EMBEDS = ["media", "link", "quote", "quote+media"]


def ranks(x):
    # Average ranks for ties.
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(len(x))
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=r)
    return sums[inv] / counts[inv]


def corr_ci(r, n, k):
    """Approximate 95% CI for a (partial) correlation with k controls."""
    if n - k - 3 <= 0 or not np.isfinite(r) or abs(r) >= 1:
        return float("nan"), float("nan")
    z, se = math.atanh(r), 1 / math.sqrt(n - k - 3)
    return math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)


def partial_spearman(x, y, controls):
    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    if controls.shape[1]:
        design = np.column_stack([np.ones(len(x)), np.apply_along_axis(ranks, 0, controls)])
        rx = rx - design @ np.linalg.lstsq(design, rx, rcond=None)[0]
        ry = ry - design @ np.linalg.lstsq(design, ry, rcond=None)[0]
    return float(np.corrcoef(rx, ry)[0, 1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="also write per-post features here")
    args = ap.parse_args()

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = [{**r, **score(r["text"])} for r in csv.DictReader(f)]
    # Drop posts that are mostly words CMUdict doesn't know (slang, names, other languages).
    rows = [r for r in rows if r["n_syllables"] >= 6 and r["oov_rate"] <= 0.3 and r["age_hours"] != ""]

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    col = lambda k: np.array([float(r[k]) for r in rows])
    controls = np.column_stack(
        [np.log1p(col("followers")), col("n_syllables"), col("age_hours")]
        + [np.array([r["embed"] == e for r in rows], dtype=float) for e in EMBEDS]
    )
    k = controls.shape[1]

    print(f"n = {len(rows)} posts")
    for o in OUTCOMES:
        y = col(o)
        print(f"  {o}: median {np.median(y):.0f}, mean {y.mean():.1f}, zero {np.mean(y == 0):.0%}")
    print(f"  followers vs likes rho = {partial_spearman(col('followers'), col('likes'), np.empty((len(rows), 0))):+.3f}"
          "  (sanity check: should be clearly positive)")

    for o in OUTCOMES:
        y = col(o)
        print(f"\n{o}:  {'feature':<16} {'raw rho':>8} {'partial rho':>12}   95% CI (partial)     n")
        for feat in FEATURES:
            x = col(feat)
            ok = np.isfinite(x)
            raw = partial_spearman(x[ok], y[ok], np.empty((ok.sum(), 0)))
            part = partial_spearman(x[ok], y[ok], controls[ok])
            lo, hi = corr_ci(part, ok.sum(), k)
            flag = " *" if np.isfinite(lo) and (lo > 0 or hi < 0) else ""
            print(f"       {feat:<16} {raw:>+8.3f} {part:>+12.3f}   [{lo:+.3f}, {hi:+.3f}]  {ok.sum():>5}{flag}")
    print("\n* CI excludes zero. With 14 features x 2 outcomes, expect ~1 false positive by chance.")


if __name__ == "__main__":
    main()

"""Within-author comparison of rhythm features: popular posts vs the same authors' ordinary posts.

For each author with at least one popular and one control post, takes
mean(feature | popular) - mean(feature | control). Reports across authors:
  - mean difference, and as a fraction of the feature's overall SD
  - 95% bootstrap CI (resampling authors)
  - two-sided sign-flip permutation p-value
A length-adjusted version first regresses each feature on syllable count
(linear + quadratic, pooled over all posts) and compares the residuals.

Usage:
    python analyze_pairs.py bsky_pairs.csv [-o scored_pairs.csv]
"""
import argparse
import csv

import numpy as np

from score_meter import score

FEATURES = ["alternation", "clash_rate", "lapse_count", "beat_regularity", "final_stressed", "fit_duple",
            "fit_triple", "segment_balance", "end_rhyme", "fit_iambic", "fit_trochaic", "fit_anapestic",
            "fit_dactylic", "pentameter_line"]
CONTEXT = ["n_syllables", "n_segments", "has_media", "has_link"]


def author_diffs(rows, values):
    """Per-author popular-minus-control mean of values (NaNs ignored)."""
    groups = {}
    for r, v in zip(rows, values):
        if np.isfinite(v):
            groups.setdefault(r["did"], {"popular": [], "control": []})[r["group"]].append(v)
    return np.array([np.mean(g["popular"]) - np.mean(g["control"])
                     for g in groups.values() if g["popular"] and g["control"]])


def summarise(d, rng, n_boot=4000, n_perm=10000):
    if len(d) < 5:
        return float("nan"), float("nan"), float("nan"), float("nan")
    boots = rng.choice(d, size=(n_boot, len(d))).mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    flips = rng.choice([-1.0, 1.0], size=(n_perm, len(d)))
    p = (np.sum(np.abs((flips * d).mean(axis=1)) >= abs(d.mean())) + 1) / (n_perm + 1)
    return d.mean(), lo, hi, p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="also write per-post features here")
    args = ap.parse_args()
    rng = np.random.default_rng(0)

    with open(args.input, newline="", encoding="utf-8") as f:
        rows = [{**r, **score(r["text"])} for r in csv.DictReader(f)]
    rows = [r for r in rows if r["n_syllables"] >= 6 and r["oov_rate"] <= 0.3]
    for r in rows:
        r["has_media"] = int("media" in r["embed"])
        r["has_link"] = int(r["embed"] == "link")

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    col = lambda k: np.array([float(r[k]) for r in rows])
    n_pop = sum(r["group"] == "popular" for r in rows)
    n_ctl = len(rows) - n_pop
    n_auth = len(author_diffs(rows, col("n_syllables")))
    pop = np.array([r["group"] == "popular" for r in rows])
    print(f"{n_pop} popular, {n_ctl} control posts; {n_auth} authors with both")
    print(f"median reposts: popular {np.median(col('reposts')[pop]):.0f}, control {np.median(col('reposts')[~pop]):.0f}; "
          f"median likes: popular {np.median(col('likes')[pop]):.0f}, control {np.median(col('likes')[~pop]):.0f}")

    print(f"\ncontext (popular minus control, within author):")
    for k in CONTEXT:
        m, lo, hi, p = summarise(author_diffs(rows, col(k)), rng)
        print(f"  {k:<16} {m:>+8.3f}  [{lo:+.3f}, {hi:+.3f}]  p={p:.3f}")

    syl = col("n_syllables")
    design = np.column_stack([np.ones(len(rows)), syl, syl ** 2])
    print(f"\n{'feature':<16} {'diff':>8} {'in SDs':>7}   95% CI             p      | length-adjusted: in SDs     p")
    for k in FEATURES:
        x = col(k)
        sd = np.nanstd(x)
        m, lo, hi, p = summarise(author_diffs(rows, x), rng)
        ok = np.isfinite(x)
        resid = np.full(len(x), np.nan)
        resid[ok] = x[ok] - design[ok] @ np.linalg.lstsq(design[ok], x[ok], rcond=None)[0]
        ma, _, _, pa = summarise(author_diffs(rows, resid), rng)
        star = " *" if p < 0.05 / len(FEATURES) else ""
        print(f"{k:<16} {m:>+8.3f} {m / sd:>+7.2f}   [{lo:+.3f}, {hi:+.3f}]  {p:.3f}{star:<2} |"
              f"                  {ma / sd:>+5.2f}  {pa:.3f}")
    print(f"\n* p < {0.05 / len(FEATURES):.4f} (Bonferroni over {len(FEATURES)} features)")


if __name__ == "__main__":
    main()

"""Score social media posts for metrical / rhythmic features.

Sketch for testing whether rhythm predicts engagement. Each post is turned
into a syllable stress string using the CMU Pronouncing Dictionary, then
summarised with a handful of rhythm features.

Usage:
    python score_meter.py posts.csv --text-col text --engagement-col likes -o scored.csv
    python score_meter.py posts.txt            # one post per line, no engagement

Stress symbols: 'S' stressed, 'u' unstressed, '?' unknown (word not in CMUdict).
"""
import argparse
import csv
import math
import re
import statistics
import sys

import pronouncing

# Monosyllabic function words are listed as stressed in CMUdict but are
# almost always unstressed in running speech.
FUNCTION_WORDS = set("""
a an the and but or nor so yet for of to in on at by with from as into onto
than that this these those is am are was were be been being do does did has
have had will would shall should can could may might must i me my we us our
you your he him his she her it its they them their who whom whose which what
if then there here not no just like up out off over
""".split())

URL_RE = re.compile(r"https?://\S+|www\.\S+")
HANDLE_RE = re.compile(r"[@#]\w+")
WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")
# Line breaks and strong punctuation mark segment (phrase) boundaries.
SEGMENT_RE = re.compile(r"[\n.!?;:—–]+|\s-\s|,")

FEET = {"iambic": "uS", "trochaic": "Su", "anapestic": "uuS", "dactylic": "Suu"}


def word_stress(word):
    """Return (stress string, in_dictionary) for one word."""
    w = word.lower()
    phones = pronouncing.phones_for_word(w)
    if not phones:
        # Unknown: estimate syllable count from vowel groups, stress unknown.
        n = max(1, len(re.findall(r"[aeiouy]+", w)) - (w.endswith("e") and len(w) > 3))
        return "?" * n, False
    # CMUdict: 1 primary, 2 secondary, 0 none. Treat secondary as stressed.
    raw = pronouncing.stresses(phones[0])
    if len(raw) == 1:
        return ("u" if w in FUNCTION_WORDS else "S"), True
    return "".join("S" if c in "12" else "u" for c in raw), True


def clean(text):
    return HANDLE_RE.sub(" ", URL_RE.sub(" ", text))


def segment_text(text):
    return [s for s in (p.strip() for p in SEGMENT_RE.split(clean(text))) if WORD_RE.search(s)]


def foot_matches(stress, foot, offset=0):
    """(matches, known syllables) for a repeating foot starting at the given phase."""
    known = [(i, c) for i, c in enumerate(stress) if c != "?"]
    return sum(c == foot[(i + offset) % len(foot)] for i, c in known), len(known)


def anchored_fit(segments, foot):
    """Fraction of syllables matching a foot that restarts at each phrase.

    Anchoring at phrase starts is what separates iambic (uS) from trochaic (Su).
    """
    hits = total = 0
    for seg in segments:
        h, n = foot_matches(seg, foot)
        hits, total = hits + h, total + n
    return hits / total if total >= 4 else float("nan")


def periodic_fit(stress, period):
    """Best fit to any duple (period 2) or triple (period 3) beat, whatever its phase."""
    foot = "S" + "u" * (period - 1)
    fits = [foot_matches(stress, foot, k) for k in range(period)]
    if fits[0][1] < 4:
        return float("nan")
    return max(h for h, _ in fits) / fits[0][1]


def interval_regularity(stress):
    """1 - coefficient of variation of gaps between stressed syllables (1 = perfectly even beat)."""
    pos = [i for i, c in enumerate(stress) if c == "S"]
    gaps = [b - a for a, b in zip(pos, pos[1:])]
    if len(gaps) < 2:
        return float("nan")
    return max(0.0, 1 - statistics.pstdev(gaps) / statistics.mean(gaps))


def rhyme_part(word):
    phones = pronouncing.phones_for_word(word.lower())
    return pronouncing.rhyming_part(phones[0]) if phones else None


def score(text):
    segments = segment_text(text)
    seg_stresses, last_words = [], []
    n_words = n_known = 0
    for seg in segments:
        words = WORD_RE.findall(seg)
        parts = [word_stress(w) for w in words]
        n_words += len(words)
        n_known += sum(ok for _, ok in parts)
        seg_stresses.append("".join(s for s, _ in parts))
        last_words.append(words[-1])

    stress = "".join(seg_stresses)
    known_pairs = [(a, b) for a, b in zip(stress, stress[1:]) if "?" not in (a, b)]
    seg_lens = [len(s) for s in seg_stresses]

    # End rhyme: any two segment-final words sharing a rhyming part (and not identical).
    rhymes = [rhyme_part(w) for w in last_words]
    has_rhyme = any(
        rhymes[i] and rhymes[i] == rhymes[j] and last_words[i].lower() != last_words[j].lower()
        for i in range(len(rhymes)) for j in range(i + 1, len(rhymes))
    )

    feats = {
        "n_words": n_words,
        "n_syllables": len(stress),
        "oov_rate": 1 - n_known / n_words if n_words else float("nan"),
        "stress_pattern": stress,
        # Fraction of adjacent syllable pairs that alternate stressed/unstressed.
        "alternation": (sum(a != b for a, b in known_pairs) / len(known_pairs)) if known_pairs else float("nan"),
        # Stress clash (SS) and lapse (uuu) are what metrical verse tends to avoid.
        "clash_rate": (sum(a == b == "S" for a, b in known_pairs) / len(known_pairs)) if known_pairs else float("nan"),
        "lapse_count": len(re.findall(r"(?=uuu)", stress)),
        "beat_regularity": interval_regularity(stress),
        "final_stressed": int(stress.endswith("S")),
        "n_segments": len(segments),
        # 1 = all phrases the same syllable length (parallelism); only meaningful with 2+ segments.
        "segment_balance": (max(0.0, 1 - statistics.pstdev(seg_lens) / statistics.mean(seg_lens))
                            if len(seg_lens) > 1 else float("nan")),
        "end_rhyme": int(has_rhyme),
    }
    feats["fit_duple"] = periodic_fit(stress, 2)
    feats["fit_triple"] = periodic_fit(stress, 3)
    for name, foot in FEET.items():
        feats[f"fit_{name}"] = anchored_fit(seg_stresses, foot)
    fits = {k: feats[f"fit_{k}"] for k in FEET}
    best = max(fits, key=lambda k: -1 if math.isnan(fits[k]) else fits[k])
    feats["best_meter"] = best if not math.isnan(fits[best]) else ""
    # Pentametron-style flag: some phrase is 10 syllables of near-iambic verse.
    feats["pentameter_line"] = int(any(
        len(s) == 10 and "?" not in s and anchored_fit([s], "uS") >= 0.8 for s in seg_stresses
    ))
    return feats


def rank(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if not (math.isnan(x) or math.isnan(y))]
    if len(pairs) < 3:
        return float("nan"), len(pairs)
    rx, ry = rank([p[0] for p in pairs]), rank([p[1] for p in pairs])
    if statistics.pstdev(rx) == 0 or statistics.pstdev(ry) == 0:
        return float("nan"), len(pairs)
    return statistics.correlation(rx, ry), len(pairs)


def load(path, text_col):
    if path.endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    with open(path, encoding="utf-8") as f:
        return [{text_col: line.rstrip("\n")} for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="CSV with a text column, or .txt with one post per line")
    ap.add_argument("--text-col", default="text")
    ap.add_argument("--engagement-col", help="numeric column (likes, reposts...) to correlate against")
    ap.add_argument("-o", "--output", help="write scored CSV here (default: stdout)")
    args = ap.parse_args()

    rows = load(args.input, args.text_col)
    scored = [{**row, **score(row[args.text_col])} for row in rows]

    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    writer = csv.DictWriter(out, fieldnames=list(scored[0].keys()))
    writer.writeheader()
    writer.writerows(scored)
    if args.output:
        out.close()

    if args.engagement_col:
        # log1p because engagement is heavy-tailed; Spearman is rank-based anyway.
        eng = [math.log1p(float(r[args.engagement_col] or 0)) for r in scored]
        numeric = [k for k, v in scored[0].items()
                   if k not in rows[0] and isinstance(v, (int, float))]
        print(f"\nSpearman correlation with log1p({args.engagement_col}):", file=sys.stderr)
        for k in numeric:
            rho, n = spearman([float(r[k]) for r in scored], eng)
            print(f"  {k:<18} rho={rho:+.3f}  n={n}", file=sys.stderr)


if __name__ == "__main__":
    main()

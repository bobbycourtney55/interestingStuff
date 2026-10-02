"""Build data/mc_outlets.csv: one row per outlet in mc_stances.jsonl with its audience lean
and a traffic measure.

Lean: Media Cloud's 2019 US partisanship collections (mc_partisanship_2019.json, from
fetch_partisanship.py), which group outlets by whether their stories were shared mostly
by Twitter followers of liberal or conservative politicians, i.e. by who reads them.
Some outlets sit in more than one group (duplicate source records); those are averaged
on a -2 (left) .. +2 (right) scale. Outlets not in any group get a lean by judgment,
marked lean_source=judgment.

Traffic: rank in the Cisco Umbrella top-1M list (umbrella-top-1m.csv.zip, ranked by DNS
query volume; best of the bare domain and www.). Lower is more traffic. It is a
popularity rank, not a visitor count, and is noisy for sites served through CDNs.
"""
import collections
import csv
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SCORE = {"left": -2, "center_left": -1, "center": 0, "center_right": 1, "right": 2}
JUDGMENT = {  # outlets missing from the 2019 collections
    "newsweek.com": "center",
    "fortune.com": "center",
    "foxbusiness.com": "right",
    "schwartzreport.net": "left",
}


def lean_from_score(s):
    if s <= -1.5:
        return "left"
    if s < -0.5:
        return "center_left"
    if s <= 0.5:
        return "center"
    if s < 1.5:
        return "center_right"
    return "right"


def group(lean):
    return {"left": "Left", "center_left": "Left", "center": "Center",
            "center_right": "Right", "right": "Right"}[lean]


def tier(rank):
    if rank is None:
        return "not in top 1M"
    for cut, label in ((25_000, "top 25K"), (100_000, "25K-100K"), (300_000, "100K-300K")):
        if rank <= cut:
            return label
    return "300K-1M"


def main():
    partisan = json.load(open(HERE / "mc_partisanship_2019.json"))
    ranks = {}
    with zipfile.ZipFile(HERE / "umbrella-top-1m.csv.zip") as z:
        for line in z.read("top-1m.csv").decode().splitlines():
            r, d = line.split(",", 1)
            ranks.setdefault(d, int(r))

    counts = collections.Counter(json.loads(l)["media_name"] for l in open(HERE.parent / "mc_stances.jsonl"))
    rows = []
    for outlet, n in counts.most_common():
        buckets = sorted(set(partisan.get(outlet, [])), key=SCORE.get)
        if buckets:
            score = sum(SCORE[b] for b in buckets) / len(buckets)
            lean, source = lean_from_score(score), "media_cloud_2019"
        else:
            lean, source = JUDGMENT[outlet], "judgment"
            score = SCORE[lean]
        found = [ranks[d] for d in (outlet, "www." + outlet) if d in ranks]
        rank = min(found) if found else None
        rows.append({
            "outlet": outlet, "headlines": n, "lean": lean, "lean_group": group(lean),
            "lean_score": round(score, 2), "mc_2019_groups": "|".join(buckets), "lean_source": source,
            "umbrella_rank": rank if rank is not None else "", "traffic_tier": tier(rank),
        })

    with open(HERE.parent / "mc_outlets.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} outlets to data/mc_outlets.csv")


if __name__ == "__main__":
    main()

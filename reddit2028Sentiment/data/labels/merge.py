"""Turn the hand-labelled batch files into data/mc_stances.jsonl (the file `report` reads).

Each batch_*.txt covers `range a b` of the headlines as ordered by show.py and lists
the positive (p), negative (n) and not-about (x) indexes; every other headline in the
range was read and judged neutral."""
import json
from pathlib import Path

import show

here = Path(__file__).parent
stance, covered = {}, set()
for f in sorted(here.glob("batch_*.txt")):
    for line in f.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "range":
            covered.update(range(int(parts[1]), int(parts[2])))
        else:
            for i in parts[1:]:
                i = int(i)
                assert i not in stance, f"index {i} labelled twice"
                stance[i] = {"p": "positive", "n": "negative", "x": "not_about"}[parts[0]]

missing = set(range(len(show.rows))) - covered
assert not missing, f"unlabelled headlines: {sorted(missing)[:10]}"
assert set(stance) <= covered, "label outside its batch range"
with open(here.parent / "mc_stances.jsonl", "w") as out:
    for i, r in enumerate(show.rows):
        out.write(json.dumps({"key": r["key"], "candidate": r["candidate"], "month": r["month"],
                              "media_name": r["media_name"], "stance": stance.get(i, "neutral"),
                              "labeler": "claude-in-session"}) + "\n")
print(f"wrote {len(show.rows)} labels:", {s: list(stance.values()).count(s) for s in ("positive", "negative", "not_about")},
      "neutral:", len(show.rows) - len(stance))

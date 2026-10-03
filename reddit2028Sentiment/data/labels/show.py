"""Print headlines start..end as 'idx|C|headline' (C = candidate code), in a fixed candidate/month order."""
import json, sys
from pathlib import Path
CODES = {"Gavin Newsom": "N", "Alexandria Ocasio-Cortez": "A", "Pete Buttigieg": "B", "Kamala Harris": "H",
         "JB Pritzker": "P", "Jon Ossoff": "O", "Ro Khanna": "K",
         "Andy Beshear": "Y"}  # appended last so earlier candidates keep their indexes
rows = [json.loads(l) for l in open(Path(__file__).parent.parent / "mc_stories.jsonl")]
rows = [r for r in rows if not r.get("empty")]
rows.sort(key=lambda r: (list(CODES).index(r["candidate"]), r["month"], r["key"]))
if __name__ == "__main__":
    a, b = int(sys.argv[1]), int(sys.argv[2])
    for i, r in enumerate(rows[a:b], a):
        print(f"{i}|{CODES[r['candidate']]}|{' '.join(r['title'].split())}")

"""Build ohio_2024_president_map.html from the county results CSV and county boundaries.

Usage: python3 build_map.py
"""
import csv
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
WIDTH = 600

rows = {}
with open(HERE / "ohio_2024_president_by_county.csv") as f:
    for r in csv.DictReader(f):
        rows[r["county_fips"]] = {
            "fips": r["county_fips"],
            "name": r["county_name"],
            "trump": int(r["votes_trump"]),
            "harris": int(r["votes_harris"]),
            "other": int(r["votes_other"]),
            "total": int(r["total_votes"]),
        }

geo = json.load(open(HERE / "ohio_counties.geojson"))

# Equirectangular projection scaled by cos(mid-latitude) so Ohio keeps its shape.
k = math.cos(math.radians(40.2))
pts = [
    (lon, lat)
    for feat in geo["features"]
    for poly in (feat["geometry"]["coordinates"] if feat["geometry"]["type"] == "MultiPolygon" else [feat["geometry"]["coordinates"]])
    for ring in poly
    for lon, lat in ring
]
min_x = min(p[0] for p in pts) * k
max_x = max(p[0] for p in pts) * k
min_y = min(p[1] for p in pts)
max_y = max(p[1] for p in pts)
scale = WIDTH / (max_x - min_x)
height = round((max_y - min_y) * scale)


def project(lon, lat):
    return round((lon * k - min_x) * scale, 1), round((max_y - lat) * scale, 1)


def path_for(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    out = []
    for poly in polys:
        for ring in poly:
            xy = [project(lon, lat) for lon, lat in ring]
            out.append("M" + "L".join(f"{x},{y}" for x, y in xy) + "Z")
    return "".join(out)


counties = []
for feat in geo["features"]:
    fips = feat["id"]
    rec = dict(rows[fips])
    rec["d"] = path_for(feat["geometry"])
    # label anchor: centroid of the projected bounding box
    xs, ys = zip(*[project(lon, lat) for lon, lat in (
        pt for poly in (feat["geometry"]["coordinates"] if feat["geometry"]["type"] == "MultiPolygon" else [feat["geometry"]["coordinates"]])
        for ring in poly for pt in ring)])
    rec["cx"] = round((min(xs) + max(xs)) / 2, 1)
    rec["cy"] = round((min(ys) + max(ys)) / 2, 1)
    counties.append(rec)
counties.sort(key=lambda c: c["name"])

template = (HERE / "map_template.html").read_text()
html = (
    template.replace("__DATA__", json.dumps(counties, separators=(",", ":")))
    .replace("__W_PAD__", str(WIDTH + 8))
    .replace("__H_PAD__", str(height + 8))
)
(HERE / "ohio_2024_president_map.html").write_text(html)
print(f"wrote ohio_2024_president_map.html ({len(counties)} counties, {WIDTH}x{height})")

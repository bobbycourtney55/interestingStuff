"""Download Media Cloud's 2019 US partisanship collections (outlets grouped by whether their
stories were shared mostly by followers of liberal vs conservative politicians on Twitter)."""
import json, os, time
import mediacloud.api

COLLECTIONS = {"left": 200363061, "center_left": 200363048, "center": 200363050,
               "center_right": 200363062, "right": 200363049}
d = mediacloud.api.DirectoryApi(os.environ["MEDIACLOUD_API_KEY"])
out = {}
for lean, cid in COLLECTIONS.items():
    offset = 0
    while True:
        for attempt in range(6):
            try:
                time.sleep(31)
                page = d.source_list(collection_id=cid, limit=1000, offset=offset)
                break
            except Exception as e:
                print("retry", str(e)[:80], flush=True); time.sleep(60)
        for s in page["results"]:
            out.setdefault(s["name"], []).append(lean)
        offset += len(page["results"])
        print(lean, offset, "/", page["count"], flush=True)
        if not page["results"] or offset >= page["count"]:
            break
json.dump(out, open(os.path.join(os.path.dirname(__file__), "mc_partisanship_2019.json"), "w"), indent=0)
print("done", len(out))

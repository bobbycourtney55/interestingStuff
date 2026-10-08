"""Profile clusters: who's in them, gift sizes, geography, PAC money, outside spending, donor occupations."""
import sys
import numpy as np, pandas as pd

D = sys.argv[1]; V = sys.argv[2] if len(sys.argv) > 2 else "all"
ct = pd.read_csv(f"{D}/cands.csv", index_col=0)
cl = pd.read_csv(f"{D}/clusters_{V}.csv", index_col=0).cluster
ct = ct.join(cl, how="inner")

cm = pd.read_csv(f"{D}/cm.txt", sep="|", header=None, dtype=str)
cm.columns = "CMTE|CNAME|TRES|A1|A2|CITY|ST|ZIP|DSGN|TP|PTY|FREQ|ORG|CONN|CAND".split("|")
cm = cm.set_index("CMTE")
p = pd.read_csv(f"{D}/itpas2.txt", sep="|", header=None, dtype=str, quoting=3)
p.columns = "CMTE|AMNDT|RPT|PGI|IMG|TT|ET|NAME|CITY|ST|ZIP|EMP|OCC|DT|AMT|OTHER|CAND|TRAN|FILE|MEMO|MEMOTXT|SUB".split("|")
p["AMT"] = pd.to_numeric(p.AMT, errors="coerce")
p = p[p.CAND.isin(ct.index)]
p["ORG"] = p.CMTE.map(cm.ORG).fillna("")
p["SPONSOR"] = p.CMTE.map(cm.CNAME)

direct = p[p.TT == "24K"]
orgmap = {"C": "corporate", "L": "labor", "T": "trade", "M": "membership", "V": "corporate", "W": "corporate"}
direct = direct.assign(kind=direct.ORG.map(orgmap).fillna("other/ideological"))
pac = direct.pivot_table(index="CAND", columns="kind", values="AMT", aggfunc="sum", fill_value=0)
ct = ct.join(pac, how="left").fillna({c: 0 for c in pac.columns})
ct["pac_total"] = pac.sum(1).reindex(ct.index).fillna(0)
ct["pac_share_of_receipts"] = ct.pac_total / (ct.pac_total + ct.tot)

ie = p[p.TT.isin(["24E", "24A"])]
ie_for = ie[ie.TT == "24E"].groupby("CAND").AMT.sum()
ct["ie_support"] = ie_for.reindex(ct.index).fillna(0)

pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 400)
for k, g in ct.groupby("cluster"):
    g = g.sort_values("n", ascending=False)
    print(f"\n=== cluster {k}: {len(g)} candidates | offices {g.OFF.value_counts().to_dict()} | ICI {g.ICI.value_counts().to_dict()}")
    print(f"states: {g.ST.value_counts().head(8).to_dict()}")
    print(f"median donors {g.n.median():.0f} | median gift ${g.median_gift.median():.0f} | in-state share {g.instate_share.median():.2f}"
          f" | PAC share of receipts {g.pac_share_of_receipts.median():.3f} | corp PAC $ median {g.get('corporate', pd.Series([0])).median():.0f}"
          f" | labor PAC $ median {g.get('labor', pd.Series([0])).median():.0f}")
    print(g[["NAME", "ST", "OFF", "DIST", "ICI", "n"]].head(25).to_string())
    # top PAC / IE sponsors relative to all clusters
    pk = direct[direct.CAND.isin(g.index)].groupby("SPONSOR").CAND.nunique().sort_values(ascending=False).head(8)
    print("most common PAC givers (# of cluster candidates):", pk.to_dict())
    ik = ie[ie.CAND.isin(g.index) & (ie.TT == "24E")].groupby("SPONSOR").AMT.sum().sort_values(ascending=False).head(6)
    print("top outside spenders FOR:", (ik / 1e6).round(2).to_dict())
ct.to_csv(f"{D}/cands_profiled_{V}.csv")

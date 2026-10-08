"""Compare donor-space dimensions with DW-NOMINATE dim 1 for incumbents."""
import sys, yaml
import numpy as np, pandas as pd
from scipy.stats import pearsonr, spearmanr

D, VV = sys.argv[1], sys.argv[2]
ct = pd.read_csv(f"{D}/cands.csv", index_col=0)
ca = pd.read_csv(f"{D}/ca_scores.csv", index_col=0)
cl = pd.read_csv(f"{D}/clusters_all.csv", index_col=0).cluster

# spectral alternative: leading non-trivial eigenvector of the normalized similarity graph
S = pd.read_parquet(f"{D}/S_all.parquet")
d = S.values.sum(1)
L = S.values / np.sqrt(np.outer(d, d))
w, v = np.linalg.eigh(L)
spec = pd.DataFrame(v[:, ::-1][:, 1:5] / np.sqrt(d)[:, None], index=S.index, columns=[f"sp{k}" for k in range(1, 5)])

fec2bio = {}
for m in yaml.safe_load(open(f"{VV}/leg.yaml")):
    for f in m["id"].get("fec", []):
        fec2bio[f] = m["id"]["bioguide"]
vv = pd.concat([pd.read_csv(f"{VV}/{c}_members.csv") for c in ["H119", "S119", "H118", "S118"]])
vv = vv[vv.chamber != "President"].sort_values("congress", ascending=False).drop_duplicates("bioguide_id")
nom = vv.set_index("bioguide_id")[["nominate_dim1", "nokken_poole_dim1", "party_code", "chamber", "congress"]]

df = ct[["NAME", "ST", "OFF", "DIST", "ICI", "n", "median_gift"]].join(ca).join(spec).join(cl)
df["bio"] = df.index.map(fec2bio)
df = df.join(nom, on="bio").dropna(subset=["nominate_dim1"])
df = df[df.party_code == 100]
print("matched Democratic members:", len(df), df.chamber.value_counts().to_dict())
for c in list(ca.columns) + list(spec.columns):
    print(f"{c}: pearson {pearsonr(df[c], df.nominate_dim1)[0]:+.2f}  spearman {spearmanr(df[c], df.nominate_dim1)[0]:+.2f}")
df.to_csv(f"{D}/nominate_merged.csv")

"""Fit CA on the well-measured core (>=500 donors), then project smaller candidates onto the same axes
as supplementary rows: each candidate's score = average standard coordinate of its donors."""
import sys
import numpy as np, pandas as pd, scipy.sparse as sp

CORE, D = sys.argv[1], sys.argv[2]
core = pd.read_csv(f"{CORE}/clusters_all.csv", index_col=0).index
allc = pd.read_csv(f"{D}/clusters_all.csv", index_col=0).index
r = pd.read_parquet(f"{D}/receipts.parquet", columns=["CAND", "DONOR"]).drop_duplicates()
ec = r[r.CAND.isin(core)]
deg = ec.groupby("DONOR").size()
ec = ec[ec.DONOR.map(deg) >= 2]
ci = {c: i for i, c in enumerate(core)}; di = {d: i for i, d in enumerate(ec.DONOR.unique())}
N = sp.csr_matrix((np.ones(len(ec)), (ec.CAND.map(ci), ec.DONOR.map(di))), shape=(len(ci), len(di)))
P = N / N.sum(); rm = np.asarray(P.sum(1)).ravel(); cm = np.asarray(P.sum(0)).ravel()
Sm = (sp.diags(1 / np.sqrt(rm)) @ P @ sp.diags(1 / np.sqrt(cm))).toarray() - np.outer(np.sqrt(rm), np.sqrt(cm))
U, s, Vt = np.linalg.svd(Sm, full_matrices=False)
G = Vt[:6].T / np.sqrt(cm)[:, None]           # donor standard coordinates
ea = r[r.CAND.isin(allc) & r.DONOR.isin(di)]
ai = {c: i for i, c in enumerate(allc)}
M = sp.csr_matrix((np.ones(len(ea)), (ea.CAND.map(ai), ea.DONOR.map(di))), shape=(len(ai), len(di)))
cnt = np.asarray(M.sum(1)).ravel()
F = (M @ G) / np.where(cnt > 0, cnt, np.nan)[:, None]
out = pd.DataFrame(F, index=allc, columns=[f"ca{k+1}" for k in range(6)])
out["core_donors_shared"] = cnt
out.to_csv(f"{D}/ca_scores.csv")
print("candidates projected:", int((cnt > 0).sum()), "of", len(allc), "| median core donors per small candidate:",
      np.median(cnt[~np.isin(allc, core)]))

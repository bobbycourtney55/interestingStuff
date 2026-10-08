"""Correspondence analysis of the candidate x donor matrix -> 1-D donor-space scores (Bonica-style)."""
import sys
import numpy as np, pandas as pd, scipy.sparse as sp
from scipy.sparse.linalg import svds

D = sys.argv[1]
cands = pd.read_csv(f"{D}/clusters_all.csv", index_col=0).index
r = pd.read_parquet(f"{D}/receipts.parquet", columns=["CAND", "DONOR"])
e = r[r.CAND.isin(cands)].drop_duplicates()
deg = e.groupby("DONOR").size()
e = e[e.DONOR.map(deg) >= 2]
ci = {c: i for i, c in enumerate(cands)}
di = {d: i for i, d in enumerate(e.DONOR.unique())}
N = sp.csr_matrix((np.ones(len(e)), (e.CAND.map(ci), e.DONOR.map(di))), shape=(len(ci), len(di)))
P = N / N.sum()
rm = np.asarray(P.sum(1)).ravel(); cm = np.asarray(P.sum(0)).ravel()
# standardized residuals S = Dr^-1/2 (P - r c') Dc^-1/2 ; dense is 287 x ~95k, fine
Sm = (sp.diags(1 / np.sqrt(rm)) @ P @ sp.diags(1 / np.sqrt(cm))).toarray() - np.outer(np.sqrt(rm), np.sqrt(cm))
U, s, Vt = np.linalg.svd(Sm, full_matrices=False)
F = (U / np.sqrt(rm)[:, None]) * s          # principal row coordinates
out = pd.DataFrame(F[:, :6], index=cands, columns=[f"ca{k+1}" for k in range(6)])
out.to_csv(f"{D}/ca_scores.csv")
print("inertia share of first 6 dims:", np.round(s[:6] ** 2 / (s ** 2).sum(), 4))

"""Cluster 2026 Dem House/Senate candidates by overlap in individual donors."""
import sys, json
import numpy as np, pandas as pd, scipy.sparse as sp, networkx as nx
from sklearn.metrics import adjusted_rand_score, silhouette_score
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

D = sys.argv[1]
MIN_DONORS = int(sys.argv[2]) if len(sys.argv) > 2 else 500
rng = np.random.default_rng(0)

r = pd.read_parquet(f"{D}/receipts.parquet")
cn = pd.read_csv(f"{D}/cn.txt", sep="|", header=None, dtype=str)
cn.columns = "CAND|NAME|PTY|YR|ST|OFF|DIST|ICI|STATUS|PCC|S1|S2|CITY|STATE|ZIP".split("|")
cn = cn.set_index("CAND")

# donor x candidate edges (one per pair), with summed amount
e = r.groupby(["CAND", "DONOR"], as_index=False).agg(AMT=("AMT", "sum"), DST=("ST", "first"))
cs = e.groupby("CAND").agg(n=("DONOR", "size"), tot=("AMT", "sum"))
keep = cs.index[cs.n >= MIN_DONORS]
e = e[e.CAND.isin(keep)]
e["instate"] = e.DST.values == cn.loc[e.CAND, "ST"].values

def build(edges):
    deg = edges.groupby("DONOR").size()
    edges = edges[edges.DONOR.map(deg) >= 2]           # single-candidate donors carry no overlap signal
    ci = {c: i for i, c in enumerate(sorted(edges.CAND.unique()))}
    di = {d: i for i, d in enumerate(edges.DONOR.unique())}
    rows = edges.CAND.map(ci).values; cols = edges.DONOR.map(di).values
    X = sp.csr_matrix((np.ones(len(edges)), (rows, cols)), shape=(len(ci), len(di)))
    return X, list(ci)

def similarity(X):
    deg = np.asarray(X.sum(0)).ravel()
    idf = np.log(X.shape[0] / deg)                      # down-weight donors who give to everyone
    W = X @ sp.diags(idf)
    nrm = np.sqrt(np.asarray(W.multiply(W).sum(1)).ravel())
    W = sp.diags(1 / np.where(nrm > 0, nrm, 1)) @ W   # candidates with no shared donors get a zero row
    S = (W @ W.T).toarray()
    np.fill_diagonal(S, 0)
    return S

def louvain(S, seed=0, res=1.0):
    G = nx.from_numpy_array(S)
    comms = nx.community.louvain_communities(G, weight="weight", resolution=res, seed=seed)
    lab = np.empty(len(S), int)
    for k, c in enumerate(sorted(comms, key=len, reverse=True)):
        lab[list(c)] = k
    return lab, nx.community.modularity(G, comms, weight="weight")

def null_model(X, seed):
    # keep each donor's number of candidates and each candidate's expected donor share; randomize who
    g = np.random.default_rng(seed)
    deg = np.asarray(X.sum(0)).ravel().astype(int)
    p = np.asarray(X.sum(1)).ravel(); p = p / p.sum()
    rows, cols = [], []
    for j, k in enumerate(deg):
        cs_ = g.choice(len(p), size=min(k, len(p)), replace=False, p=p)
        rows += list(cs_); cols += [j] * len(cs_)
    return sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=X.shape)

out = {}
for variant, edges in [("all", e), ("out_of_state", e[~e.instate]), ("over200", e[e.AMT > 200])]:
    X, cands = build(edges)
    S = similarity(X)
    lab, Q = louvain(S)
    # stability across Louvain seeds and donor bootstraps
    seeds_ari = [adjusted_rand_score(lab, louvain(S, seed=s)[0]) for s in range(1, 6)]
    boot = []
    for b in range(5):
        don = rng.random(X.shape[1]) < 0.8
        boot.append(adjusted_rand_score(lab, louvain(similarity(X[:, don]), seed=b)[0]))
    nullQ = [louvain(similarity(null_model(X, s)))[1] for s in range(3)]
    Dm = 1 - S; np.fill_diagonal(Dm, 0); Dm = np.clip(Dm, 0, None)
    sil = silhouette_score(Dm, lab, metric="precomputed") if len(set(lab)) > 1 else np.nan
    st = cn.loc[cands, "ST"].values
    out[variant] = dict(n_cands=len(cands), n_donors=X.shape[1], n_clusters=int(lab.max() + 1),
                        modularity=Q, null_modularity=nullQ, seed_ari=seeds_ari, boot_ari=boot,
                        silhouette=sil, ari_vs_state=adjusted_rand_score(st, lab))
    print(variant, json.dumps(out[variant], default=float, indent=1))
    pd.DataFrame(S, index=cands, columns=cands).to_parquet(f"{D}/S_{variant}.parquet")
    pd.Series(lab, index=cands, name="cluster").to_csv(f"{D}/clusters_{variant}.csv")

# candidate table
ct = cs.loc[keep].join(cn[["NAME", "ST", "OFF", "DIST", "ICI", "STATUS"]])
ct["instate_share"] = e.groupby("CAND").instate.mean()
ct["median_gift"] = r[r.CAND.isin(keep)].groupby("CAND").AMT.median()
ct.to_csv(f"{D}/cands.csv")
json.dump(out, open(f"{D}/summary.json", "w"), default=float, indent=1)

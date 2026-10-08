"""Heatmap of donor-overlap similarity between candidates, ordered by cluster."""
import sys
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

D, OUT = sys.argv[1], sys.argv[2]
S = pd.read_parquet(f"{D}/S_all.parquet")
cl = pd.read_csv(f"{D}/clusters_all.csv", index_col=0).cluster.loc[S.index]
names = {0: "National small-dollar", 1: "Frontline House", 2: "Big-dollar establishment",
         3: "Progressive left", 4: "New-candidate professionals", 5: "CO / KS / AR",
         6: "WA / HI", 7: "Physician network"}
# within cluster, order by connectedness so the densest core sits at the block corner
strength = S.sum(1)
order = sorted(S.index, key=lambda c: (cl[c], -strength[c]))
M = S.loc[order, order].values
cmap = LinearSegmentedColormap.from_list("seq", ["#fcfcfb", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
fig, ax = plt.subplots(figsize=(9.5, 9), dpi=150)
im = ax.imshow(M, cmap=cmap, vmin=0, vmax=np.quantile(M, 0.99), interpolation="nearest")
sizes = cl.value_counts().sort_index().values
edges = np.concatenate([[0], np.cumsum(sizes)]) - 0.5
for a, b in zip(edges[:-1], edges[1:]):
    ax.add_patch(plt.Rectangle((a, a), b - a, b - a, fill=False, ec="#3a3a38", lw=0.9))
mids = (edges[:-1] + edges[1:]) / 2
ax.set_yticks(mids, [f"{names[k]} ({n})" for k, n in enumerate(sizes)], fontsize=9, color="#3a3a38")
ax.set_xticks([])
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0)
cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
cb.set_label("Donor-overlap similarity (IDF-weighted cosine)", fontsize=9, color="#3a3a38")
cb.outline.set_visible(False)
ax.set_title("2026 Democratic House & Senate candidates, by shared individual donors\n"
             "287 candidates with ≥500 itemized donors · FEC bulk data through Oct 4, 2026",
             fontsize=11, loc="left", color="#1d1d1b")
fig.tight_layout()
fig.savefig(OUT, facecolor="white")

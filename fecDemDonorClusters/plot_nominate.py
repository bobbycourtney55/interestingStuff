"""Scatter: DW-NOMINATE dim 1 vs donor-space position (both as percentile among matched Dems)."""
import sys
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

D, OUT = sys.argv[1], sys.argv[2]
df = pd.read_csv(f"{D}/nominate_merged.csv", index_col=0)
fig, ax = plt.subplots(figsize=(8.5, 7.5), dpi=150)
ax.scatter(df.p_nom * 100, df.p_don * 100, s=34, c="#2a78d6", ec="white", lw=1, zorder=3)
b = np.polyfit(df.p_nom * 100, df.p_don * 100, 1); x = np.array([0, 100])
ax.plot(x, np.polyval(b, x), color="#8a8a86", lw=1.5, ls="--", zorder=2)
lab = pd.concat([df.nlargest(6, "resid"), df.nsmallest(6, "resid")])
for _, r in lab.iterrows():
    last = r.NAME.split(",")[0].title()
    off = (-8, -12) if last == "Wasserman Schultz" else (5, 3)
    ax.annotate(last, (r.p_nom * 100, r.p_don * 100), xytext=off, ha="right" if off[0] < 0 else "left", textcoords="offset points", fontsize=8.5, color="#3a3a38")
ax.set_xlabel("DW-NOMINATE dim 1, percentile among Democrats  (← more liberal votes · more moderate votes →)", fontsize=9, color="#3a3a38")
ax.set_ylabel("Donor-network position, percentile  (← small-dollar/left donors · big-dollar/establishment →)", fontsize=9, color="#3a3a38")
ax.set_xlim(-2, 102); ax.set_ylim(-2, 102)
ax.grid(color="#e6e5e1", lw=0.8); ax.set_axisbelow(True)
for s in ["top", "right"]: ax.spines[s].set_visible(False)
for s in ["left", "bottom"]: ax.spines[s].set_color("#bdbcb7")
ax.tick_params(colors="#5c5c58", labelsize=8.5)
ax.set_title(f"Voting record vs. donor network, {len(df)} Democratic members of Congress\n"
             f"Spearman ρ = {spearmanr(df.p_nom, df.p_don)[0]:.2f} · labeled: 6 largest outliers each way", fontsize=11, loc="left", color="#1d1d1b")
fig.tight_layout(); fig.savefig(OUT, facecolor="white")

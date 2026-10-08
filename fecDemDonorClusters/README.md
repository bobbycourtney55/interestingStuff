# Do 2026 Democratic candidates cluster by donor?

Source: FEC bulk files for the 2025–26 cycle (`indiv26`, `pas226`, `cn26`, `ccl26`, `cm26`). The data runs through Oct 4, 2026.

Method: the scripts in this folder build candidate × donor overlap from itemized individual contributions to the principal and authorized committees of Democratic House and Senate candidates on the 2026 ballot. A donor is matched as last name + first name + ZIP5. Donors are weighted by IDF, so people who give to everyone count less. Candidates are compared by cosine similarity and grouped with Louvain community detection. The analysis covers the 287 candidates with at least 500 itemized donors.

Run order: `filter.sh DATA` → `prep.py DATA` → `analyze.py DATA 500` → `profile.py DATA` → `plot.py DATA out.png`

Result: the structure is real. Modularity is 0.25, against ~0.01 for a randomized network with the same sizes. The groups are reproducible (ARI ~0.75 under donor resampling, 0.79 when limited to donors who gave over $200). But the boundaries overlap rather than being cleanly separated (silhouette ≈ 0.02). See `donor_overlap_heatmap.png` and `candidates_by_cluster.csv`.

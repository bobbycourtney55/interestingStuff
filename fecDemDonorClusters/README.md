# Do 2026 Democratic candidates cluster by donor?

Source: FEC bulk files for the 2025–26 cycle (`indiv26`, `pas226`, `cn26`, `ccl26`, `cm26`). The data runs through Oct 4, 2026.

Method: the scripts in this folder build candidate × donor overlap from itemized individual contributions to the principal and authorized committees of Democratic House and Senate candidates on the 2026 ballot. A donor is matched as last name + first name + ZIP5. Donors are weighted by IDF, so people who give to everyone count less. Candidates are compared by cosine similarity and grouped with Louvain community detection. The analysis covers the 287 candidates with at least 500 itemized donors.

Run order: `filter.sh DATA` → `prep.py DATA` → `analyze.py DATA 500` → `profile.py DATA` → `plot.py DATA out.png`

Result: the structure is real. Modularity is 0.25, against ~0.01 for a randomized network with the same sizes. The groups are reproducible (ARI ~0.75 under donor resampling, 0.79 when limited to donors who gave over $200). But the boundaries overlap rather than being cleanly separated (silhouette ≈ 0.02). See `donor_overlap_heatmap.png` and `candidates_by_cluster.csv`.

## Donor position vs. DW-NOMINATE

`ca.py` runs correspondence analysis on the same candidate × donor matrix, the approach behind Bonica-style donor scores. Its first dimension is the "donor left-right" line. `nominate.py` matches candidates to Voteview DW-NOMINATE dim 1 (119th Congress, with the 118th as a fallback). The FEC-to-bioguide crosswalk comes from unitedstates/congress-legislators.

Across 127 Democratic members the correlation is Spearman 0.34 (Pearson 0.27). The donor axis tracks median gift size strongly (ρ = 0.62), but the link to NOMINATE holds after controlling for gift size (partial ρ = 0.30). See `nominate_vs_donors.png` and `nominate_merged.csv`. The `resid` column holds each member's outlier score.

## Rerun with a lower cutoff (`cutoff150/`)

The 500-donor cutoff dropped 104 of 213 Democratic House incumbents, mostly safe-seat members who only itemize donors over $200 (DeLauro, Courtney, Himes and others). This folder reruns everything at ≥150 donors: 569 candidates, 190 of them House incumbents.

Clusters (`analyze.py DATA 150`): modularity is still 0.24, against ~0.02 for the random null, and resampling stability is ARI ~0.63. The four main clusters carry over (ARI 0.64 on the 287 shared candidates). The establishment cluster grows to 139 candidates and becomes the home of safe-seat incumbents (98 of them; PAC money is 39% of receipts). The "new-candidate professionals" cluster from the 500 run breaks up. Several small regional clusters appear.

Donor line vs. DW-NOMINATE: refitting correspondence analysis on all 569 candidates gives a first axis dominated by small, peripheral candidates. So `ca_supp.py` fits the axis on the 287 well-measured candidates and places the rest on it from their donors. Across 211 members the correlation is Spearman 0.26: 0.34 on the original 127, 0.18 on the 84 newly added.

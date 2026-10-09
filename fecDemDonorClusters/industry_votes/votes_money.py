"""Does an industry's money predict Democrats' votes on that industry's issues, and does money follow the vote?

For each vote:
  1. logit(pro-industry vote) ~ pre-vote industry money + DW-NOMINATE dim 1 + other business-PAC money
  2. placebo: the same model using each *other* industry's pre-vote money
  3. OLS: post-vote industry money/month ~ vote + pre-vote industry money + NOMINATE + business-PAC money
"""
import sys, yaml, warnings
import numpy as np, pandas as pd, statsmodels.formula.api as smf

warnings.filterwarnings("ignore")
D, VV = sys.argv[1], sys.argv[2]
START, END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-09-30")

# (chamber, rollnumber, industry, label, pro-industry cast is yea?)
VOTES = [
    ("H", 198, "crypto", "CLARITY Act (crypto market structure)", True),
    ("H", 199, "crypto", "GENIUS Act (stablecoins)", True),
    ("H", 70, "crypto", "Repeal IRS crypto-broker reporting rule", True),
    ("S", 318, "crypto", "GENIUS Act, Senate passage", True),
    ("S", 102, "crypto", "Repeal IRS crypto-broker rule, Senate", True),
    ("H", 113, "oil_gas_auto", "Revoke California EV waiver", True),
    ("S", 30, "oil_gas_auto", "Confirm Chris Wright (Energy Sec.)", True),
    ("H", 261, "defense", "FY26 NDAA, House passage", True),
    ("S", 570, "defense", "FY26 NDAA, Senate passage", True),
    ("S", 166, "pro_israel", "Block Israel arms sale (Apr 2025)", False),
    ("S", 455, "pro_israel", "Block Israel arms sale (Jul 2025)", False),
    ("S", 454, "pro_israel", "Block Israel arms export (Jul 2025)", False),
    ("S", 740, "pro_israel", "Block Israel arms sale (Apr 2026)", False),
]
INDUSTRIES = ["crypto", "oil_gas_auto", "defense", "pro_israel"]

fec = {m["id"]["bioguide"]: m["id"].get("fec", []) for m in yaml.safe_load(open(f"{VV}/leg.yaml"))}
money = pd.read_parquet(f"{D}/industry_money.parquet")
money = money[money.kind != "ie_oppose"]                 # count only money spent for the member

# generic business-PAC money (corporate / trade / membership / coop PACs) as a "business-friendly" control
cmo = pd.read_csv(f"{D}/cm.txt", sep="|", header=None, dtype=str).set_index(0)[12]
pas = pd.read_csv(f"{D}/itpas2.txt", sep="|", header=None, dtype=str, quoting=3)
pas = pas[(pas[5] == "24K") & pas[0].map(cmo).isin(["C", "T", "M", "V", "W"])]
biz = pd.DataFrame({"CAND": pas[16].values, "DT": pd.to_datetime(pas[13], format="%m%d%Y", errors="coerce").values,
                    "AMT": pd.to_numeric(pas[14], errors="coerce").values}).dropna()

def by_member(frame, ids_list, cutoff):
    """sum of frame.AMT before / from cutoff for each member's list of FEC candidate ids"""
    idx = {c: i for i, ids in enumerate(ids_list) for c in ids}
    f = frame[frame.CAND.isin(idx)]
    who = f.CAND.map(idx).values
    pre = np.bincount(who[f.DT.values < cutoff], weights=f.AMT.values[f.DT.values < cutoff], minlength=len(ids_list))
    post = np.bincount(who[f.DT.values >= cutoff], weights=f.AMT.values[f.DT.values >= cutoff], minlength=len(ids_list))
    return pre, post

def asinh_month(x, months):
    return np.arcsinh(x / max(months, 1) / 100)          # ~log of monthly $ for large values, defined at 0

rows, detail = [], []
for ch, rn, ind, label, yea_is_pro in VOTES:
    c = {"H": "H119", "S": "S119"}[ch]
    mem = pd.read_csv(f"{VV}/{c}_members.csv"); mem = mem[mem.party_code == 100]
    rc = pd.read_csv(f"{VV}/{c}_rollcalls.csv").set_index("rollnumber").loc[rn]
    vdate = np.datetime64(pd.Timestamp(rc.date))
    v = pd.read_csv(f"{VV}/{c}_votes.csv"); v = v[(v.rollnumber == rn) & v.cast_code.isin([1, 2, 3, 4, 5, 6])]
    df = mem.merge(v[["icpsr", "cast_code"]], on="icpsr")
    df["pro"] = ((df.cast_code <= 3) == yea_is_pro).astype(int)
    df["nom"] = df.nominate_dim1
    ids = [fec.get(b, []) for b in df.bioguide_id]
    m_pre = (pd.Timestamp(rc.date) - START).days / 30.4; m_post = (END - pd.Timestamp(rc.date)).days / 30.4
    for k in INDUSTRIES:
        pre, post = by_member(money[money.ind == k], ids, vdate)
        df[f"pre_{k}"], df[f"post_{k}"] = pre, post
        df[f"x_{k}"] = asinh_month(pre, m_pre)
    bpre, _ = by_member(biz, ids, vdate)
    ipac_pre, _ = by_member(money[(money.ind == ind) & (money.kind == "pac")], ids, vdate)
    df["x_biz"] = asinh_month(bpre - ipac_pre, m_pre)       # business PACs excluding this industry's own
    df["x_pre"] = df[f"x_{ind}"]; df["x_post"] = asinh_month(df[f"post_{ind}"], m_post)
    df["pre"], df["post"] = df[f"pre_{ind}"], df[f"post_{ind}"]

    out = dict(vote=label, chamber=ch, date=rc.date, industry=ind, n=len(df), pro_share=df.pro.mean(),
               n_money=int((df.pre > 0).sum()), pro_if_money=df[df.pre > 0].pro.mean(), pro_if_none=df[df.pre == 0].pro.mean())
    def fit(x):
        try:
            lg = smf.logit(f"pro ~ {x} + nom + x_biz", df).fit(disp=0)
            hi = df.assign(**{x: df.loc[df[x] > 0, x].median()}); lo = df.assign(**{x: 0})
            return 100 * (lg.predict(hi) - lg.predict(lo)).mean(), lg.pvalues[x]
        except Exception:
            return np.nan, np.nan
    out["ame_pp"], out["p"] = fit("x_pre")
    for k in INDUSTRIES:
        if k != ind:
            out[f"placebo_{k}_pp"], out[f"placebo_{k}_p"] = fit(f"x_{k}")
    ols = smf.ols("x_post ~ pro + x_pre + nom + x_biz", df).fit(cov_type="HC1")
    out["post_coef"], out["post_p"] = ols.params.pro, ols.pvalues.pro
    out["post_med_pro"], out["post_med_anti"] = df[df.pro == 1].post.median(), df[df.pro == 0].post.median()
    rows.append(out)
    detail.append(df.assign(vote=label, industry=ind)[["vote", "industry", "bioname", "state_abbrev", "nom", "pro", "pre", "post"]])

res = pd.DataFrame(rows)
pd.set_option("display.width", 260, "display.max_columns", 40)
print(res[["vote", "n", "pro_share", "n_money", "pro_if_money", "pro_if_none", "ame_pp", "p",
           "post_med_pro", "post_med_anti", "post_coef", "post_p"]].round(3).to_string())
print(res[["vote"] + [c for c in res.columns if c.startswith("placebo")]].round(3).to_string())
res.to_csv(f"{D}/votes_money_summary.csv", index=False)
pd.concat(detail).to_csv(f"{D}/votes_money_members.csv", index=False)

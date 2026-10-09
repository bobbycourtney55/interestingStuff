"""Follow-ups: joint crypto + pro-Israel model; post-vote placebo; what kind of crypto money followed the vote."""
import sys, warnings
import numpy as np, pandas as pd, statsmodels.formula.api as smf
warnings.filterwarnings("ignore")
sys.argv = [sys.argv[0]] + sys.argv[1:]
exec(open(sys.argv[0].replace("votes_followup.py", "votes_money.py")).read().split("rows, detail = [], []")[0])

def member_frame(ch, rn, yea_is_pro):
    c = {"H": "H119", "S": "S119"}[ch]
    mem = pd.read_csv(f"{VV}/{c}_members.csv"); mem = mem[mem.party_code == 100]
    rc = pd.read_csv(f"{VV}/{c}_rollcalls.csv").set_index("rollnumber").loc[rn]
    v = pd.read_csv(f"{VV}/{c}_votes.csv"); v = v[(v.rollnumber == rn) & v.cast_code.isin([1, 2, 3, 4, 5, 6])]
    df = mem.merge(v[["icpsr", "cast_code"]], on="icpsr")
    df["pro"] = ((df.cast_code <= 3) == yea_is_pro).astype(int); df["nom"] = df.nominate_dim1
    ids = [fec.get(b, []) for b in df.bioguide_id]; vd = np.datetime64(pd.Timestamp(rc.date))
    mp = (pd.Timestamp(rc.date) - START).days / 30.4; mq = (END - pd.Timestamp(rc.date)).days / 30.4
    for k in INDUSTRIES:
        pre, post = by_member(money[money.ind == k], ids, vd)
        df[f"x_{k}"], df[f"y_{k}"] = asinh_month(pre, mp), asinh_month(post, mq)
        for kind in ["pac", "employees", "conduit", "ie_support"]:
            _, pk = by_member(money[(money.ind == k) & (money.kind == kind)], ids, vd)
            df[f"post_{k}_{kind}"] = pk
    bpre, bpost = by_member(biz, ids, vd)
    df["x_biz"], df["y_biz"] = asinh_month(bpre, mp), asinh_month(bpost, mq)
    return df

for ch, rn, label in [("H", 198, "CLARITY"), ("H", 199, "GENIUS"), ("H", 70, "IRS crypto rule")]:
    df = member_frame(ch, rn, True)
    lg = smf.logit("pro ~ x_crypto + x_pro_israel + nom + x_biz", df).fit(disp=0)
    print(f"\n{label}: joint logit coefs (p):", {k: f"{lg.params[k]:+.2f} ({lg.pvalues[k]:.3f})" for k in ["x_crypto", "x_pro_israel", "nom", "x_biz"]})
    print("  corr(pre crypto, pre pro-Israel) =", round(df[["x_crypto", "x_pro_israel"]].corr().iloc[0, 1], 2))
    for y in ["y_crypto", "y_pro_israel", "y_oil_gas_auto", "y_defense", "y_biz"]:
        x = "x_" + y[2:]
        o = smf.ols(f"{y} ~ pro + {x} + nom", df).fit(cov_type="HC1")
        print(f"  post-vote {y[2:]:13s} ~ voted pro: {o.params.pro:+.2f} (p={o.pvalues.pro:.3f})")
    yes = df[df.pro == 1]; no = df[df.pro == 0]
    for kind in ["pac", "employees", "ie_support"]:
        col = f"post_crypto_{kind}"
        print(f"  post-vote crypto {kind:10s}: yes-voters total ${yes[col].sum():>12,.0f} ({(yes[col]>0).mean():.0%} got any) | no-voters ${no[col].sum():>12,.0f} ({(no[col]>0).mean():.0%})")

df = member_frame("H", 113, True)
print("\nEV waiver: post-vote placebo")
for y in ["y_oil_gas_auto", "y_crypto", "y_defense", "y_biz"]:
    o = smf.ols(f"{y} ~ pro + x_{y[2:]} + nom", df).fit(cov_type="HC1")
    print(f"  post-vote {y[2:]:13s} ~ voted pro: {o.params.pro:+.2f} (p={o.pvalues.pro:.3f})")
print(" yes voters:", df[df.pro == 1].bioname.str.split(",").str[0].tolist())
print(" yes-voter states:", df[df.pro == 1].state_abbrev.value_counts().to_dict())
lg = smf.logit("pro ~ x_oil_gas_auto + nom + x_biz + I(state_abbrev.isin(['MI','TX','OH','IN','LA','OK']))", df).fit(disp=0)
print(" with auto/oil-state dummy: oil_gas_auto coef", round(lg.params.x_oil_gas_auto, 2), "p", round(lg.pvalues.x_oil_gas_auto, 3))

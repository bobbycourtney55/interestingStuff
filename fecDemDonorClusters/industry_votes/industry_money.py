"""Tag 2025-26 money to Democratic members by industry, with dates, from PAC, individual, conduit and IE records."""
import sys, re
import pandas as pd, numpy as np

D = sys.argv[1]
IND = {
 "crypto": r"COINBASE|RIPPLE(?! OF HOPE)|CRYPTO|BLOCKCHAIN|DIGITAL CHAMBER|FAIRSHAKE|PROTECT PROGRESS|DEFEND AMERICAN JOBS|STAND WITH CRYPTO|KRAKEN|PAYWARD|CIRCLE INTERNET|GEMINI TRUST|ANDREESSEN|\bA16Z\b|PARADIGM OPERATIONS|BITCOIN|ETHEREUM|SOLANA|TETHER|ANCHORAGE DIGITAL|CHAINALYSIS|CONSENSYS|GALAXY DIGITAL|MICROSTRATEGY|BINANCE|ROBINHOOD|UNISWAP|DIGITAL ASSET",
 "oil_gas_auto": r"EXXON|CHEVRON|CONOCO|MARATHON PETROLEUM|VALERO|PHILLIPS 66|OCCIDENTAL PETROLEUM|\bHESS\b|DEVON ENERGY|PIONEER NATURAL|EOG RESOURCES|AMERICAN PETROLEUM|INDEPENDENT PETROLEUM|AMERICAN FUEL|NATURAL GAS SUPPLY|INTERSTATE NATURAL GAS|PETROLEUM|OIL CO|OIL &|OIL AND GAS|ENERGY TRANSFER|KINDER MORGAN|WILLIAMS COMPANIES|ENBRIDGE|\bBP\b|SHELL USA|SHELL OIL|CHENIERE|HALLIBURTON|BAKER HUGHES|SCHLUMBERGER|GENERAL MOTORS|FORD MOTOR|STELLANTIS|TOYOTA|HONDA|HYUNDAI|AUTOMOBILE DEALERS|AUTO DEALERS|AUTOMOTIVE INNOVATION|AUTO INNOVATORS",
 "defense": r"LOCKHEED|RAYTHEON|\bRTX\b|GENERAL DYNAMICS|ELECTRIC BOAT|NORTHROP|BOEING|L3HARRIS|L-3|HUNTINGTON INGALLS|BAE SYSTEMS|LEIDOS|BOOZ ALLEN|SCIENCE APPLICATIONS|\bSAIC\b|PALANTIR|ANDURIL|TEXTRON|BELL TEXTRON|GENERAL ATOMICS|PRATT & WHITNEY|SIKORSKY|OSHKOSH|AEROJET|MANTECH|CACI|PARSONS CORP|AEROSPACE INDUSTRIES|NATIONAL DEFENSE INDUSTRIAL|SHIELD AI",
 "pro_israel": r"AMERICAN ISRAEL PUBLIC AFFAIRS|UNITED DEMOCRACY PROJECT|NORPAC|PRO-ISRAEL AMERICA|DEMOCRATIC MAJORITY FOR ISRAEL|DMFI|JOINT ACTION COMMITTEE FOR POLITICAL|JACPAC|^WASHINGTON PAC\b|FRIENDS OF ISRAEL|ISRAEL ALLIES",
}
# J Street is tracked separately: it backs aid conditions that pro-Israel PACs above oppose
IND["jstreet"] = r"JSTREET|J STREET"

cm = pd.read_csv(f"{D}/cm.txt", sep="|", header=None, dtype=str)
cm["label"] = (cm[1].fillna("") + " | " + cm[13].fillna("")).str.upper()
def tag(s):
    for k, rx in IND.items():
        if re.search(rx, s): return k
    return None
cm["ind"] = cm.label.map(tag)
cmind = cm.set_index(0).ind.dropna()

p = pd.read_csv(f"{D}/itpas2.txt", sep="|", header=None, dtype=str, quoting=3)
p.columns = "CMTE|AMNDT|RPT|PGI|IMG|TT|ET|NAME|CITY|ST|ZIP|EMP|OCC|DT|AMT|OTHER|CAND|TRAN|FILE|MEMO|MEMOTXT|SUB".split("|")
p["ind"] = p.CMTE.map(cmind)
p = p[p.ind.notna() & p.TT.isin(["24K", "24E", "24A"])]
p["kind"] = p.TT.map({"24K": "pac", "24E": "ie_support", "24A": "ie_oppose"})
rows = [p[["CAND", "ind", "kind", "DT", "AMT"]]]

cols = "CAND|CMTE_ID|AMNDT|RPT|PGI|IMG|TT|ET|NAME|CITY|ST|ZIP|EMP|OCC|DT|AMT|OTHER|TRAN|FILE|MEMO|MEMOTXT|SUB".split("|")
x = pd.read_csv(f"{D}/dem_indiv.txt", sep="|", header=None, names=cols, dtype=str, quoting=3, on_bad_lines="skip",
                usecols=["CAND", "TT", "ET", "EMP", "DT", "AMT", "OTHER", "MEMO"])
x = x[(x.ET == "IND") & x.TT.isin(["15", "15E"]) & (x.MEMO != "X")]
emp = x.EMP.fillna("").str.upper()
uniq = pd.Series(emp.unique()); uniq_tag = dict(zip(uniq, uniq.map(lambda s: tag(s) if s else None)))
x["emp_ind"] = emp.map(uniq_tag)
x["conduit_ind"] = x.OTHER.map(cmind)            # e.g. earmarked through AIPAC PAC or JStreetPAC
a = x[x.emp_ind.notna()].assign(ind=lambda d: d.emp_ind, kind="employees")
b = x[x.conduit_ind.notna()].assign(ind=lambda d: d.conduit_ind, kind="conduit")
rows += [a[["CAND", "ind", "kind", "DT", "AMT"]], b[["CAND", "ind", "kind", "DT", "AMT"]]]

m = pd.concat(rows)
m["AMT"] = pd.to_numeric(m.AMT, errors="coerce")
m["DT"] = pd.to_datetime(m.DT, format="%m%d%Y", errors="coerce")
m = m.dropna(subset=["AMT", "DT"])
m.to_parquet(f"{D}/industry_money.parquet")
print(m.groupby(["ind", "kind"]).AMT.agg(["size", "sum"]).round(0))
for k in IND:
    print(k, "PACs:", cm[cm.ind == k][1].head(12).tolist())
    print("   employers:", emp[x.emp_ind == k].value_counts().head(10).to_dict())

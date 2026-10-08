"""Build donor-level table for 2026 Dem House/Senate candidates from filtered itcont rows."""
import sys, re
import pandas as pd
import numpy as np

D = sys.argv[1]
cols = ("CAND|CMTE_ID|AMNDT|RPT|PGI|IMG|TT|ET|NAME|CITY|ST|ZIP|EMP|OCC|DT|AMT|OTHER|TRAN|FILE|MEMO|MEMOTXT|SUB").split("|")
df = pd.read_csv(f"{D}/dem_indiv.txt", sep="|", header=None, names=cols, dtype=str,
                 usecols=["CAND", "TT", "ET", "NAME", "ST", "ZIP", "EMP", "OCC", "AMT", "MEMO", "PGI"],
                 quoting=3, on_bad_lines="skip")
print("raw rows", len(df))
df = df[(df.ET == "IND") & df.TT.isin(["15", "15E"]) & (df.MEMO != "X")]
df["AMT"] = pd.to_numeric(df.AMT, errors="coerce")
df = df[df.AMT > 0]
print("individual receipts", len(df))

def norm_name(n):
    n = re.sub(r"[^A-Z, ]", "", str(n).upper())
    last, _, first = n.partition(",")
    last = last.strip().split(" ")
    first = first.strip().split(" ")
    # drop suffixes / titles
    drop = {"JR", "SR", "II", "III", "IV", "MR", "MRS", "MS", "DR", "MD"}
    last = [t for t in last if t and t not in drop]
    first = [t for t in first if t and t not in drop]
    return (last[-1] if last else "") + "|" + (first[0] if first else "")

names = df.NAME.unique()
nm = dict(zip(names, map(norm_name, names)))
df["DONOR"] = df.NAME.map(nm) + "|" + df.ZIP.str[:5].fillna("")
df = df[~df.DONOR.str.startswith("|")]
df[["CAND", "DONOR", "ST", "AMT", "EMP", "OCC"]].to_parquet(f"{D}/receipts.parquet")
print("unique donors", df.DONOR.nunique(), "candidates", df.CAND.nunique())

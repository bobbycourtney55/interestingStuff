"""Normalize and SHA-256 hash customer fields the way Meta's Custom Audience
API expects (https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences#hash).

Values that already look like a SHA-256 hex digest are passed through, so
hashing can alternatively be done in BigQuery with TO_HEX(SHA256(...)) as long
as the same normalization rules are applied there first.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from typing import Any, Mapping, Sequence

# Keys Meta accepts in a multi-key schema.
HASHED_KEYS = ("EMAIL", "PHONE", "FN", "LN", "FI", "CT", "ST", "ZIP",
               "COUNTRY", "GEN", "DOBY", "DOBM", "DOBD")
UNHASHED_KEYS = ("EXTERN_ID", "MADID")
# Pseudo key: a DATE/datetime/"YYYY-MM-DD" column split into DOBY/DOBM/DOBD.
DOB = "DOB"
# Keys that can identify someone by themselves; a row needs at least one.
IDENTIFYING_KEYS = {"EMAIL", "PHONE", "MADID", "EXTERN_ID", "LN"}

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "districtofcolumbia": "dc", "florida": "fl", "georgia": "ga", "hawaii": "hi",
    "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me",
    "maryland": "md", "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "newhampshire": "nh", "newjersey": "nj", "newmexico": "nm",
    "newyork": "ny", "northcarolina": "nc", "northdakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "rhodeisland": "ri",
    "southcarolina": "sc", "southdakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "westvirginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}
COUNTRY_ALIASES = {
    "usa": "us", "unitedstates": "us", "unitedstatesofamerica": "us",
    "uk": "gb", "unitedkingdom": "gb", "greatbritain": "gb",
    "canada": "ca", "australia": "au", "mexico": "mx", "germany": "de",
    "france": "fr",
}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value)).strip().lower()


def _letters(value: Any) -> str:
    """Lowercase, letters only (Unicode letters kept, Meta wants them UTF-8)."""
    return "".join(c for c in _text(value) if c.isalpha())


def norm_email(value: Any) -> str | None:
    v = _text(value)
    return v if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) else None


def norm_phone(value: Any, default_cc: str | None = None) -> str | None:
    raw = str(value).strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if raw.startswith("+"):
        return digits
    if digits.startswith("00"):          # international dialing prefix
        return digits[2:] or None
    if default_cc:
        national = digits.lstrip("0")    # trunk prefix, e.g. UK 07... -> 7...
        # NANP numbers come as 10 digits; anything already starting with the
        # country code and longer than a national number is left as is.
        if not (digits.startswith(default_cc) and len(digits) > 10):
            return default_cc + national
    return digits.lstrip("0") or None


def norm_state(value: Any) -> str | None:
    v = _letters(value)
    return US_STATES.get(v, v) or None


def norm_zip(value: Any, country: str | None) -> str | None:
    v = re.sub(r"[\s\-]", "", _text(value))
    if not v:
        return None
    if country in (None, "us") and re.fullmatch(r"\d{5}(\d{4})?", v):
        return v[:5]
    if country == "us" and v.isdigit() and len(v) < 5:   # lost leading zeros
        return v.zfill(5)
    return v


def norm_country(value: Any) -> str | None:
    v = _letters(value)
    v = COUNTRY_ALIASES.get(v, v)
    return v if len(v) == 2 else None


def norm_gender(value: Any) -> str | None:
    v = _text(value)[:1]
    return v if v in ("m", "f") else None


def split_dob(value: Any) -> tuple[str, str, str] | None:
    if isinstance(value, (dt.date, dt.datetime)):
        d = value
    else:
        try:
            d = dt.date.fromisoformat(str(value).strip()[:10])
        except ValueError:
            return None
    return f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}"


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def expand_schema(columns: Mapping[str, str], default_country: str | None) -> list[str]:
    """Meta schema (ordered key list) for a config `columns` mapping."""
    schema: list[str] = []
    for key in columns:
        key = key.upper()
        if key == DOB:
            schema += ["DOBY", "DOBM", "DOBD"]
        elif key in HASHED_KEYS or key in UNHASHED_KEYS:
            schema.append(key)
        else:
            raise ValueError(f"Unsupported Meta schema key: {key}")
    if default_country and "COUNTRY" not in schema:
        schema.append("COUNTRY")
    if len(set(schema)) != len(schema):
        raise ValueError(f"Duplicate keys in schema: {schema}")
    return schema


def build_row(record: Mapping[str, Any], columns: Mapping[str, str],
              schema: Sequence[str], *, default_country: str | None = None,
              default_phone_cc: str | None = None) -> list[str] | None:
    """Turn one BigQuery row into a Meta `data` row aligned with `schema`.

    Returns None when nothing usable to match on is left after normalization.
    """
    raw = {k.upper(): record.get(col) for k, col in columns.items()}
    out: dict[str, str | None] = {}

    country = None
    if not _blank(raw.get("COUNTRY")):
        country = norm_country(raw["COUNTRY"])
    country = country or (default_country.lower() if default_country else None)
    if "COUNTRY" in schema:
        out["COUNTRY"] = country

    for key, value in raw.items():
        if key == "COUNTRY" or _blank(value):
            continue
        text = _text(value)
        if key in HASHED_KEYS and _SHA256_HEX.match(text):
            out[key] = text          # already hashed upstream
            continue
        if key == "EMAIL":
            out[key] = norm_email(value)
        elif key == "PHONE":
            out[key] = norm_phone(value, default_phone_cc)
        elif key in ("FN", "LN", "CT"):
            out[key] = _letters(value) or None
            if key == "FN" and "FI" in schema and out[key] and "FI" not in raw:
                out["FI"] = out[key][0]
        elif key == "FI":
            out[key] = _letters(value)[:1] or None
        elif key == "ST":
            out[key] = norm_state(value)
        elif key == "ZIP":
            out[key] = norm_zip(value, country)
        elif key == "GEN":
            out[key] = norm_gender(value)
        elif key == DOB:
            parts = split_dob(value)
            if parts:
                out["DOBY"], out["DOBM"], out["DOBD"] = parts
        elif key == "DOBY":
            out[key] = text if re.fullmatch(r"\d{4}", text) else None
        elif key in ("DOBM", "DOBD"):
            out[key] = text.zfill(2) if re.fullmatch(r"\d{1,2}", text) else None
        elif key in UNHASHED_KEYS:
            out[key] = str(value).strip()

    if not any(out.get(k) for k in IDENTIFYING_KEYS):
        return None

    row = []
    for key in schema:
        v = out.get(key)
        if not v:
            row.append("")       # Meta wants "" for a missing field
        elif key in UNHASHED_KEYS or _SHA256_HEX.match(v):
            row.append(v)
        else:
            row.append(sha256(v))
    return row

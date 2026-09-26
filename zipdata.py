"""Ground the assumptions in real data for a ZIP code.

Sources, all free and keyless:
  * Zippopotam.us            -> city / state for a ZIP
  * Zillow ZHVI (public CSV) -> typical home value, and its 5-year growth rate
  * Zillow ZORI (public CSV) -> typical asking rent, and its 5-year growth rate
  * A bundled state table    -> effective property tax rate

Honesty matters more than coverage here, so every field comes back with its own `source` and
`asof`, and the UI shows them. Measured-for-this-ZIP and estimated-from-the-state are NOT the
same thing and shouldn't look the same.

The ZHVI file is ~124 MB, so it is downloaded once and trimmed to the last few years of columns;
after that lookups are served from the small local cache.
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data")
os.makedirs(CACHE, exist_ok=True)

ZHVI_URL = ("https://files.zillowstatic.com/research/public_csvs/zhvi/"
            "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv")
ZORI_URL = ("https://files.zillowstatic.com/research/public_csvs/zori/"
            "Zip_zori_uc_sfrcondomfr_sm_month.csv")
CACHE_DAYS = 30
MONTHS_KEPT = 73          # six years + 1, enough for a 5-year growth rate

# Effective property tax rate on owner-occupied homes, % of value, by state. State AVERAGES —
# county and city rates vary a lot within a state, so this is a starting point, not an answer.
# Order-of-magnitude source: Tax Foundation / ATTOM annual effective-rate tables.
STATE_PROPERTY_TAX = {
    "AL": 0.40, "AK": 1.04, "AZ": 0.63, "AR": 0.62, "CA": 0.75, "CO": 0.51, "CT": 1.79,
    "DE": 0.58, "DC": 0.57, "FL": 0.82, "GA": 0.92, "HI": 0.32, "ID": 0.67, "IL": 2.07,
    "IN": 0.84, "IA": 1.52, "KS": 1.41, "KY": 0.85, "LA": 0.56, "ME": 1.24, "MD": 1.05,
    "MA": 1.14, "MI": 1.38, "MN": 1.11, "MS": 0.79, "MO": 0.97, "MT": 0.74, "NE": 1.63,
    "NV": 0.55, "NH": 1.93, "NJ": 2.23, "NM": 0.78, "NY": 1.64, "NC": 0.80, "ND": 0.98,
    "OH": 1.53, "OK": 0.90, "OR": 0.93, "PA": 1.53, "RI": 1.40, "SC": 0.57, "SD": 1.17,
    "TN": 0.67, "TX": 1.68, "UT": 0.57, "VT": 1.83, "VA": 0.82, "WA": 0.94, "WV": 0.58,
    "WI": 1.73, "WY": 0.61,
}


def _fresh(path: str) -> bool:
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_DAYS * 86400


def _slim_path(name: str) -> str:
    return os.path.join(CACHE, f"{name}_slim.csv")


def _download_and_trim(url: str, name: str, timeout: int = 180) -> str:
    """Stream the big CSV once, keeping only the ZIP id columns + the last MONTHS_KEPT months."""
    out = _slim_path(name)
    if _fresh(out):
        return out
    req = urllib.request.Request(url, headers={"User-Agent": "rent-vs-buy/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    header = rows[0]
    date_start = next(i for i, c in enumerate(header) if c[:2] == "20" and "-" in c)
    keep_meta = [i for i, c in enumerate(header)
                 if c in ("RegionName", "State", "City", "Metro", "CountyName")]
    keep_dates = list(range(max(date_start, len(header) - MONTHS_KEPT), len(header)))
    idx = keep_meta + keep_dates
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            if len(r) >= len(header):
                w.writerow([r[i] for i in idx])
    return out


def _series_for_zip(name: str, url: str, zipcode: str):
    """(dates, values) for one ZIP, or (None, None) if the ZIP isn't in the file."""
    try:
        path = _download_and_trim(url, name)
    except Exception:
        return None, None
    z = zipcode.zfill(5)
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        try:
            zi = header.index("RegionName")
        except ValueError:
            return None, None
        dates = [c for c in header if c[:2] == "20" and "-" in c]
        d0 = header.index(dates[0])
        for row in r:
            if row[zi].zfill(5) == z:
                vals = [(float(v) if v not in ("", None) else None) for v in row[d0:]]
                return dates, vals
    return None, None


def _latest(dates, vals):
    for d, v in zip(reversed(dates), reversed(vals)):
        if v is not None:
            return d, v
    return None, None


def _cagr(dates, vals, years=5):
    """Annualised growth over the last `years` of the series, as a percent."""
    d_end, v_end = _latest(dates, vals)
    if v_end is None:
        return None, None
    end_i = dates.index(d_end)
    start_i = max(0, end_i - years * 12)
    d_start, v_start = dates[start_i], vals[start_i]
    if not v_start:
        pairs = [(d, v) for d, v in zip(dates[:end_i], vals[:end_i]) if v]
        if not pairs:
            return None, None
        d_start, v_start = pairs[0]
        start_i = dates.index(d_start)
    span_years = (end_i - start_i) / 12
    if span_years <= 0 or v_start <= 0:
        return None, None
    return ((v_end / v_start) ** (1 / span_years) - 1) * 100, f"{d_start[:7]} to {d_end[:7]}"


def lookup_zip(zipcode: str) -> dict:
    zipcode = "".join(ch for ch in str(zipcode) if ch.isdigit()).zfill(5)[:5]
    out = {"zip": zipcode, "fields": {}, "place": None, "warnings": []}

    # --- where is it ---
    state_abbr = None
    try:
        req = urllib.request.Request(f"https://api.zippopotam.us/us/{zipcode}",
                                     headers={"User-Agent": "rent-vs-buy/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            place = json.load(r)["places"][0]
        state_abbr = place["state abbreviation"]
        out["place"] = f'{place["place name"]}, {state_abbr}'
    except Exception:
        out["warnings"].append("Couldn't identify that ZIP code.")

    def put(key, value, source, asof, estimated=False, digits=2):
        if value is None:
            return
        out["fields"][key] = {"value": round(float(value), digits), "source": source,
                              "asof": asof, "estimated": estimated}

    # --- home value + appreciation (measured for this ZIP) ---
    dates, vals = _series_for_zip("zhvi", ZHVI_URL, zipcode)
    if dates:
        d, v = _latest(dates, vals)
        put("home_price", v, "Zillow ZHVI (typical home value, this ZIP)", d[:7], digits=0)
        g, span = _cagr(dates, vals)
        put("home_appreciation_pct", g, f"Zillow ZHVI 5-year growth, this ZIP", span, digits=1)
    else:
        out["warnings"].append("No Zillow home-value history for this ZIP.")

    # --- rent + rent growth (measured for this ZIP) ---
    dates, vals = _series_for_zip("zori", ZORI_URL, zipcode)
    if dates:
        d, v = _latest(dates, vals)
        put("monthly_rent", v, "Zillow ZORI (typical asking rent, this ZIP)", d[:7], digits=0)
        g, span = _cagr(dates, vals)
        put("rent_growth_pct", g, "Zillow ZORI 5-year growth, this ZIP", span, digits=1)
    else:
        out["warnings"].append("No Zillow rent history for this ZIP.")

    # --- property tax (state average, NOT this ZIP) ---
    if state_abbr and state_abbr in STATE_PROPERTY_TAX:
        put("property_tax_rate_pct", STATE_PROPERTY_TAX[state_abbr],
            f"{state_abbr} state average — your county may differ", "2024", estimated=True, digits=2)

    return out

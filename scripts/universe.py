#!/usr/bin/env python3
"""
Rebuild data/universe.csv — the list of stocks the scanner covers.

Universe = every S&P 500 member  UNION  every US-listed common stock above a
market-cap floor (default $5B).  Names, sectors and index tags come from two
public datasets that are refreshed daily, so this script is safe to run on a
schedule and needs no API key.

Sources
  - S&P 500 membership + GICS sectors:
      github.com/datasets/s-and-p-500-companies
  - All NASDAQ / NYSE / AMEX listings with market cap + sector:
      github.com/rreichel3/US-Stock-Symbols  (mirrors the Nasdaq screener)

Usage:  python3 scripts/universe.py [--min-cap 5e9]
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "universe.csv")

SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
LISTING_URLS = {
    "NASDAQ": "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_full_tickers.json",
    "NYSE": "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_full_tickers.json",
    "AMEX": "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/amex/amex_full_tickers.json",
}

# Nasdaq's sector vocabulary -> GICS-style names, so both sources agree.
SECTOR_MAP = {
    "Technology": "Information Technology",
    "Finance": "Financials",
    "Basic Materials": "Materials",
    "Telecommunications": "Communication Services",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Health Care": "Health Care",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Miscellaneous": "Other",
    "": "Other",
}

# The Nasdaq screener files a lot of things under "Consumer Discretionary" that
# GICS would not (engineering firms, freight, packaging, oilfield gear).  These
# industry keywords override the file's sector; first match wins.  S&P 500 names
# always keep their real GICS sector and never reach this table.
INDUSTRY_OVERRIDES = [
    ("Industrials", ["business services", "diversified commercial", "professional services",
                     "engineering", "military", "industrial machinery", "metal fabrications",
                     "marine transportation", "air freight", "delivery services", "transportation services",
                     "railroads", "trucking", "aerospace", "pollution control", "environmental",
                     "building products", "construction/ag equipment", "electrical products",
                     "wholesale distributors"]),
    ("Materials", ["containers/packaging", "paper", "forest products", "steel", "aluminum",
                   "major chemicals", "specialty chemicals", "agricultural chemicals",
                   "precious metals", "mining"]),
    ("Energy", ["oil and gas field machinery", "oilfield services", "oil & gas production",
                "integrated oil", "coal mining", "natural gas distribution"]),
    ("Information Technology", ["telecommunications equipment", "semiconductors",
                                "computer manufacturing", "electronic components",
                                "computer software", "edp services"]),
    ("Health Care", ["medical/dental instruments", "biotechnology", "major pharmaceuticals",
                     "medical specialities", "hospital/nursing management"]),
    ("Real Estate", ["real estate investment trusts", "real estate"]),
    ("Financials", ["major banks", "investment managers", "property-casualty insurers",
                    "life insurance", "finance companies", "investment bankers"]),
    ("Utilities", ["power generation", "electric utilities", "water supply"]),
]


def override_sector(sector, industry):
    ind = (industry or "").lower()
    if not ind:
        return sector
    for target, keys in INDUSTRY_OVERRIDES:
        if any(k in ind for k in keys):
            return target
    return sector


# Instruments that are not ordinary shares.
BAD_NAME = re.compile(
    r"\b(warrants?|rights?|preferred|depositary|debentures?|notes?|"
    r"etf|etn|fund|index|trust series|royalty trust|municipal|"
    r"subordinated|convertible)\b|%",
    re.I,
)
BAD_SYMBOL = re.compile(r"[\^$]")

# Everything after these words is corporate boilerplate, not the company name.
NAME_TAIL = re.compile(
    r"\s*[-,]?\s*(common stock|ordinary shares?|common shares?|class [a-c]"
    r"|cl [a-c]|capital stock|shares of beneficial interest|american depositary"
    r"|\(the\)|\(reit\)|new|when issued).*$",
    re.I,
)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 linreg-scanner"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def clean_name(raw):
    n = NAME_TAIL.sub("", raw or "").strip(" -,")
    n = re.sub(r"\s+", " ", n)
    return n or raw


def yahoo_symbol(sym):
    """Nasdaq writes share classes as BRK/B; Yahoo wants BRK-B."""
    return sym.replace("/", "-").replace(".", "-")


def display_symbol(sym):
    return sym.replace("/", ".")


def build(min_cap):
    # --- S&P 500 (authoritative membership + GICS sector) -------------------
    sp = {}
    for row in csv.DictReader(io.StringIO(get(SP500_URL))):
        s = (row.get("Symbol") or "").strip()
        if not s:
            continue
        sp[s.replace(".", "/")] = {
            "name": (row.get("Security") or s).strip(),
            "sector": (row.get("GICS Sector") or "Other").strip(),
        }
    print(f"S&P 500 constituents: {len(sp)}")

    # --- all US listings (market cap + sector) ------------------------------
    listings = []
    for exch, url in LISTING_URLS.items():
        rows = json.loads(get(url))
        for r in rows:
            r["exchange"] = exch
        listings += rows
        print(f"{exch} listings: {len(rows)}")

    out = {}
    for r in listings:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym or BAD_SYMBOL.search(sym):
            continue
        try:
            cap = float(r.get("marketCap") or 0)
        except ValueError:
            cap = 0.0
        in_sp = sym in sp
        if not in_sp:
            if cap < min_cap:
                continue
            if BAD_NAME.search(r.get("name") or ""):
                continue

        if in_sp:
            sector = sp[sym]["sector"]
        else:
            sector = SECTOR_MAP.get((r.get("sector") or "").strip(), "Other")
            sector = override_sector(sector, r.get("industry"))
        name = sp[sym]["name"] if in_sp else clean_name(r.get("name"))

        if cap >= 200e9:
            tier = "Mega cap"
        elif cap >= 10e9:
            tier = "Large cap"
        elif cap >= 2e9:
            tier = "Mid cap"
        elif cap > 0:
            tier = "Small cap"
        else:
            tier = "Unknown"

        out[sym] = {
            "symbol": display_symbol(sym),
            "yahoo": yahoo_symbol(sym),
            "name": name,
            "sector": sector or "Other",
            "exchange": r.get("exchange", ""),
            "sp500": "1" if in_sp else "0",
            "tier": tier,
            "market_cap": int(cap),
        }

    # S&P 500 members that the listings file missed (rare; keep them anyway)
    for sym, meta in sp.items():
        if sym not in out:
            out[sym] = {
                "symbol": display_symbol(sym),
                "yahoo": yahoo_symbol(sym),
                "name": meta["name"],
                "sector": meta["sector"],
                "exchange": "",
                "sp500": "1",
                "tier": "Unknown",
                "market_cap": 0,
            }
            print(f"  (added missing S&P member {sym})")

    rows = sorted(out.values(), key=lambda d: -d["market_cap"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["symbol", "yahoo", "name", "sector", "exchange", "sp500", "tier", "market_cap"]
        )
        w.writeheader()
        w.writerows(rows)
    n_sp = sum(1 for d in rows if d["sp500"] == "1")
    print(f"wrote {OUT}: {len(rows)} symbols ({n_sp} S&P 500, {len(rows) - n_sp} other)")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cap", type=float, default=float(os.environ.get("MIN_MARKET_CAP", 5e9)))
    a = ap.parse_args()
    try:
        build(a.min_cap)
    except Exception as e:  # noqa: BLE001
        print(f"universe build failed: {e}", file=sys.stderr)
        sys.exit(1)

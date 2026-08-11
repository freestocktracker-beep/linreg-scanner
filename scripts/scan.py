#!/usr/bin/env python3
"""
Linear-regression channel scan across three timeframes.

Replicates TradingView's "Linear Regression Channel" (length 100, source =
close, 2 standard deviations) on the DAILY, WEEKLY and MONTHLY timeframes, for
every symbol in data/universe.csv.

One 10-year daily pull per symbol is resampled locally into weekly and monthly
bars — the resampled closes match Yahoo's own weekly/monthly series exactly, and
one request per symbol is far gentler than three.  Because the pull carries full
OHLC, the site can draw candles as well as lines.

Writes, per timeframe TF in {1d, 1wk, 1mo}:
  data/latest-TF.json        ranked rows + summary stats     (small, always loaded)
  data/series/TF/X.json      OHLC bars (SERIES_BARS per timeframe), bucketed by
                             first character — more than the channel needs, so
                             the chart can pan back past the regression window
  data/history-TF.json       channel position over time      (committed; accumulates)
  data/alerts.json           new bottom-of-channel crossings, keyed by timeframe

Usage:  python3 scripts/scan.py [--limit N] [--timeframes 1d,1wk,1mo]
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import random
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

LENGTH = 100            # regression length, in bars (TradingView default)
DEVS = 2.0              # standard deviations for the channel bands

# How much price history to publish per timeframe. The channel is always fitted
# on the last LENGTH bars, but the chart lets you pan back past that, so we ship
# more bars than the maths needs. These numbers are a size trade-off: the whole
# bucket file downloads when a reader opens their first chart for that letter,
# so daily stops at roughly nineteen months rather than the full ten years.
SERIES_BARS = {"1d": 400, "1wk": 260, "1mo": 120}
BOTTOM_ZONE = 15.0      # "at/near bottom" threshold, in % of channel height
WORKERS = 10
HISTORY_DAYS = 400      # rolling window of position snapshots we keep

# Per timeframe: label, how many bars before we call the history thin, and how
# many past bars to seed the position history with on a fresh install.
TIMEFRAMES = {
    "1d":  {"name": "Daily",   "min_bars": 120, "thin_bars": 250, "backfill": 60},
    "1wk": {"name": "Weekly",  "min_bars": 60,  "thin_bars": 150, "backfill": 52},
    "1mo": {"name": "Monthly", "min_bars": 24,  "thin_bars": 60,  "backfill": 36},
}
DEFAULT_TF = "1mo"

# Reference instruments run through the identical channel maths, so "9% of its
# channel" can be read against where the market and the stock's own sector sit.
# Scanned alongside the universe but kept out of the ranking.
INDEX_BENCHMARKS = [
    ("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("DIA", "Dow 30"), ("IWM", "Russell 2000"),
]
SECTOR_ETF = {
    "Information Technology": ("XLK", "Tech sector"),
    "Health Care": ("XLV", "Health Care sector"),
    "Financials": ("XLF", "Financials sector"),
    "Consumer Discretionary": ("XLY", "Cons. Discretionary sector"),
    "Consumer Staples": ("XLP", "Consumer Staples sector"),
    "Energy": ("XLE", "Energy sector"),
    "Industrials": ("XLI", "Industrials sector"),
    "Materials": ("XLB", "Materials sector"),
    "Real Estate": ("XLRE", "Real Estate sector"),
    "Utilities": ("XLU", "Utilities sector"),
    "Communication Services": ("XLC", "Comm. Services sector"),
}

UA = {"User-Agent": "Mozilla/5.0 (compatible; linreg-scanner/2.0)"}


# --------------------------------------------------------------------------- io
def fetch(url, timeout=45, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            if getattr(e, "code", None) in (400, 404):   # unknown symbol
                break
            time.sleep((2 ** i) + random.random())
    raise last


def daily_bars(symbol):
    """(bars, dividends) — ten years of split-adjusted daily bars plus ex-div dates.

    Dividends ride along on the same request, so they cost nothing extra.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?range=10y&interval=1d&events=div%2Csplit")
    res = ((fetch(url).get("chart") or {}).get("result") or [None])[0]
    if not res:
        return [], []
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c = (q.get(k) or [] for k in ("open", "high", "low", "close"))
    out = []
    for i, t in enumerate(ts):
        cc = c[i] if i < len(c) else None
        if cc is None:
            continue
        oo = o[i] if i < len(o) and o[i] is not None else cc
        hh = h[i] if i < len(h) and h[i] is not None else max(oo, cc)
        ll = l[i] if i < len(l) and l[i] is not None else min(oo, cc)
        out.append((dt.datetime.utcfromtimestamp(t).date(), oo, hh, ll, cc))

    divs = []
    for d in ((res.get("events") or {}).get("dividends") or {}).values():
        if d.get("date") is not None and d.get("amount") is not None:
            divs.append([dt.datetime.utcfromtimestamp(d["date"]).date().isoformat(),
                         round(float(d["amount"]), 4)])
    divs.sort()
    return out, divs


# --- next earnings date ------------------------------------------------------
# Yahoo gates quoteSummary behind a cookie + crumb pair. It is cheap to obtain
# once per run and the whole thing is best-effort: no crumb, no earnings marker,
# everything else still works.
_CRUMB = {"value": None, "opener": None}

# The consent/crumb pages are served to browsers; a library UA gets turned away.
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def yahoo_crumb():
    if _CRUMB["value"] is not None:
        return _CRUMB["value"]
    import http.cookiejar
    try:
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        # fc.yahoo.com answers 404 but sets the session cookies the crumb is tied
        # to — the error response is what we're after, not the body.
        try:
            op.open(urllib.request.Request("https://fc.yahoo.com", headers=BROWSER_UA), timeout=20).read()
        except Exception:  # noqa: BLE001
            pass
        crumb = op.open(urllib.request.Request("https://query1.finance.yahoo.com/v1/test/getcrumb",
                                               headers=BROWSER_UA), timeout=20).read().decode("utf-8", "replace").strip()
        _CRUMB["opener"] = op
        _CRUMB["value"] = crumb if crumb and "<" not in crumb and len(crumb) < 40 else ""
    except Exception as e:  # noqa: BLE001
        print(f"  (crumb fetch failed: {e})")
        _CRUMB["value"] = ""
    return _CRUMB["value"]


def next_earnings(symbol):
    """ISO date of the next scheduled report, or None. Best effort."""
    crumb = yahoo_crumb()
    if not crumb:
        return None
    import gzip
    import urllib.parse
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
           f"?modules=calendarEvents&crumb={urllib.parse.quote(crumb)}")
    try:
        raw = _CRUMB["opener"].open(urllib.request.Request(url, headers=BROWSER_UA), timeout=20).read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        res = ((json.loads(raw.decode("utf-8", "replace")).get("quoteSummary") or {}).get("result") or [None])[0]
        dates = (((res or {}).get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or []
        for d in dates:
            if d.get("fmt"):
                return d["fmt"]
    except Exception:  # noqa: BLE001
        return None
    return None


def williams_r(high, low, close, period=14):
    """Williams %R: 0 at the top of the recent range, -100 at the bottom."""
    out = []
    for i in range(len(close)):
        j = max(0, i - period + 1)
        hh, ll = max(high[j:i + 1]), min(low[j:i + 1])
        out.append(None if hh == ll else round((hh - close[i]) / (hh - ll) * -100, 1))
    return out


def resample(bars, tf):
    """Daily bars -> (labels, opens, highs, lows, closes) for the given timeframe.

    Open is the period's first open, close its last close, high/low the extremes —
    the standard aggregation, and the one that reproduces Yahoo's own weekly and
    monthly series.
    """
    if tf == "1d":
        return ([b[0].isoformat() for b in bars],
                [b[1] for b in bars], [b[2] for b in bars],
                [b[3] for b in bars], [b[4] for b in bars])

    def key(d):
        if tf == "1wk":
            y, w, _ = d.isocalendar()
            return (y, w)
        return (d.year, d.month)

    def label(d):
        if tf == "1wk":
            y, w, _ = d.isocalendar()
            return dt.date.fromisocalendar(y, w, 1).isoformat()
        return f"{d.year:04d}-{d.month:02d}"

    labels, o, h, l, c = [], [], [], [], []
    cur = None
    for d, bo, bh, bl, bc in bars:
        k = key(d)
        if k != cur:
            cur = k
            labels.append(label(d))
            o.append(bo)
            h.append(bh)
            l.append(bl)
            c.append(bc)
        else:
            h[-1] = max(h[-1], bh)
            l[-1] = min(l[-1], bl)
            c[-1] = bc
    return labels, o, h, l, c


# ---------------------------------------------------------------------- the math
def linreg(closes):
    """TradingView LinReg channel over the last LENGTH closes."""
    y = closes[-LENGTH:]
    n = len(y)
    idx = range(n)
    sx = sum(idx)
    sy = sum(y)
    sxx = sum(i * i for i in idx)
    sxy = sum(i * y[i] for i in idx)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    dev = math.sqrt(sum((y[i] - (intercept + slope * i)) ** 2 for i in idx) / n)
    if dev == 0:
        return None

    mx, my = sx / n, sy / n
    cov = sum((i - mx) * (y[i] - my) for i in idx)
    vx = sum((i - mx) ** 2 for i in idx)
    vy = sum((v - my) ** 2 for v in y)
    r = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0

    mid = intercept + slope * (n - 1)
    upper, lower = mid + DEVS * dev, mid - DEVS * dev
    price = y[-1]

    state, swings = 0, 0
    for i in idx:
        p = (y[i] - (intercept + slope * i - DEVS * dev)) / (2 * DEVS * dev) * 100
        if p >= 80:
            state = 1
        elif p <= 20:
            if state == 1:
                swings += 1
            state = -1

    return dict(
        pos=round((price - lower) / (upper - lower) * 100, 1),
        r=round(r, 3), slope=round(slope, 4), price=round(price, 2),
        lower=round(lower, 2), mid=round(mid, 2), upper=round(upper, 2),
        bars=n, swings=swings,
    )


ON_BAND = 5.0           # within this many points of a band counts as sitting on it


def zone(p):
    """Where price stands, with a tight band either side of each edge — sitting
    ON the lower band is the signal this scanner exists to find, so it gets its
    own name rather than being lumped in with the bottom 15%."""
    if p < -ON_BAND:
        return "Below lower band"
    if p <= ON_BAND:
        return "On the lower band"
    if p <= 15:
        return "Near the bottom"
    if p <= 35:
        return "Lower third"
    if p <= 65:
        return "Mid-channel"
    if p <= 85:
        return "Upper third"
    if p < 100 - ON_BAND:
        return "Near the top"
    if p <= 100 + ON_BAND:
        return "On the upper band"
    return "Above upper band"


def strength(r):
    a = abs(r)
    return ("Very strong" if a >= 0.85 else "Strong" if a >= 0.70
            else "Moderate" if a >= 0.50 else "Weak" if a >= 0.30 else "Choppy / none")


# ------------------------------------------------------------------- per symbol
def scan_symbol(meta, timeframes, want_earnings=True):
    """One network call, three channels. Returns {tf: (row, series, closes)} or {}."""
    try:
        bars, divs = daily_bars(meta["yahoo"])
    except Exception:  # noqa: BLE001
        return {}
    if len(bars) < 40:
        return {}
    earn = next_earnings(meta["yahoo"]) if want_earnings else None

    # distance from the 52-week high, from the daily bars (same for every timeframe)
    highs = [b[2] for b in bars[-252:]]
    hi52 = round((bars[-1][4] / max(highs) - 1) * 100, 1) if highs and max(highs) > 0 else None

    out = {}
    for tf in timeframes:
        cfg = TIMEFRAMES[tf]
        labels, o, h, l, c = resample(bars, tf)
        if len(c) < cfg["min_bars"]:
            continue
        m = linreg(c)
        if not m:
            continue
        k = min(SERIES_BARS.get(tf, LENGTH), len(c))
        m.update(
            sym=meta["symbol"], name=meta["name"], sector=meta["sector"],
            sp500=meta["sp500"] == "1", tier=meta["tier"],
            cap=int(meta["market_cap"] or 0),
            zone=zone(m["pos"]),
            dir="Uptrend" if m["slope"] > 0 else ("Downtrend" if m["slope"] < 0 else "Flat"),
            strength=strength(m["r"]),
            thin=len(c) < cfg["thin_bars"],
            kind=meta.get("kind"),
            earn=earn,          # on the row too, so the UI has it before series load
        )
        wr = williams_r(h, l, c)
        # quick-read fields for the table: bar-over-bar change, latest %R, drawdown
        m["chg"] = round((c[-1] / c[-2] - 1) * 100, 2) if len(c) >= 2 and c[-2] else None
        m["wr"] = wr[-1]
        m["hi52"] = hi52
        first = labels[-k]
        out[tf] = (m, {
            "t": labels[-k:],
            "o": [round(v, 2) for v in o[-k:]],
            "h": [round(v, 2) for v in h[-k:]],
            "l": [round(v, 2) for v in l[-k:]],
            "c": [round(v, 2) for v in c[-k:]],
            "wr": wr[-k:],
            "div": [x for x in divs if x[0] >= first],
            "earn": earn,
        }, c)
    return out


# ------------------------------------------------------------------------- main
def load_universe(limit=None):
    with open(os.path.join(DATA, "universe.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit] if limit else rows


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def bucket_of(sym):
    ch = sym[0].upper()
    return ch if "A" <= ch <= "Z" else "_"


def bar_date(label):
    """A bar label -> the date the bar closed on. '2026-08' -> '2026-08-31'."""
    if len(label) == 7:                                   # monthly, YYYY-MM
        y, m = (int(x) for x in label.split("-"))
        nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
        return (nxt - dt.timedelta(days=1)).isoformat()
    return label                                          # daily / weekly already ISO


def backfill(series_by_sym, closes_by_sym, tf, periods):
    """Seed history by re-running the regression as it stood at each past bar.

    Each point is computed only from the data available at the time, so the
    seeded curve is what the scanner would have reported back then — not today's
    channel applied to old prices.
    """
    min_bars = TIMEFRAMES[tf]["min_bars"]
    pos = {}
    for sym, closes in closes_by_sym.items():
        tail = series_by_sym[sym]["t"]          # labels for the last len(tail) bars
        n, k = len(closes), len(tail)
        for back in range(periods, 0, -1):
            if back > k - 1 or n - back < min_bars:
                continue
            m = linreg(closes[: n - back])
            if m:
                pos.setdefault(sym, {})[bar_date(tail[k - back - 1])] = m["pos"]
    dates = sorted({d for v in pos.values() for d in v})
    return {"dates": dates, "pos": {s: [v.get(d) for d in dates] for s, v in pos.items()}}


def benchmark_universe():
    """The reference ETFs, shaped like universe rows so they scan identically."""
    rows = []
    for sym, name in INDEX_BENCHMARKS:
        rows.append({"symbol": sym, "yahoo": sym, "name": name, "sector": "Benchmark",
                     "sp500": "0", "tier": "Index", "market_cap": "0", "kind": "index"})
    for sector, (sym, name) in sorted(SECTOR_ETF.items()):
        rows.append({"symbol": sym, "yahoo": sym, "name": name, "sector": sector,
                     "sp500": "0", "tier": "Sector", "market_cap": "0", "kind": "sector"})
    return rows


def median(vals):
    v = sorted(vals)
    return round(v[len(v) // 2], 3) if v else None


def aggregates(rows):
    """Universe-wide and per-sector medians, so every stat has something to sit against."""
    def block(rs):
        return {
            "n": len(rs),
            "pos": median([d["pos"] for d in rs]),
            "r": median([abs(d["r"]) for d in rs]),
            "swings": median([d["swings"] for d in rs]),
            "up": round(100 * sum(1 for d in rs if d["dir"] == "Uptrend") / len(rs)) if rs else None,
        }
    by_sector = {}
    for d in rows:
        by_sector.setdefault(d["sector"], []).append(d)
    return {"all": block(rows), "sectors": {k: block(v) for k, v in by_sector.items()}}


def run(limit=None, timeframes=("1d", "1wk", "1mo"), outdir=DATA):
    uni = load_universe(limit)
    bench = benchmark_universe()
    bench_syms = {b["symbol"] for b in bench}
    uni = [u for u in uni if u["symbol"] not in bench_syms] + bench
    print(f"scanning {len(uni)} symbols ({len(bench)} benchmarks) across {', '.join(timeframes)}…")

    rows = {tf: [] for tf in timeframes}
    series = {tf: {} for tf in timeframes}
    closes = {tf: {} for tf in timeframes}
    ok = 0

    want_earn = os.environ.get("SCAN_EARNINGS", "1") != "0"
    if want_earn and not yahoo_crumb():
        print("  (no Yahoo crumb — earnings dates will be skipped this run)")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, res in enumerate(ex.map(lambda m: scan_symbol(m, timeframes, want_earn), uni)):
            if res:
                ok += 1
            for tf, (row, ser, full) in res.items():
                rows[tf].append(row)
                series[tf][row["sym"]] = ser
                closes[tf][row["sym"]] = full
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(uni)} symbols, {time.time() - t0:.0f}s")

    print(f"fetched {ok}/{len(uni)} symbols in {time.time() - t0:.0f}s")
    if ok < 0.8 * len(uni):
        print("ERROR: fewer than 80% of symbols returned data — refusing to publish", file=sys.stderr)
        sys.exit(2)

    today = dt.datetime.now(dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=-4))).date().isoformat()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_alerts, seeded_any = {}, False

    for tf in timeframes:
        allrows = sorted(rows[tf], key=lambda d: d["pos"])
        bench_rows = [d for d in allrows if d.get("kind")]
        r = [d for d in allrows if not d.get("kind")]
        for i, d in enumerate(r, 1):
            d["rank"] = i

        # ---- history --------------------------------------------------------
        hpath = os.path.join(outdir, f"history-{tf}.json")
        hist = read_json(hpath, {"dates": [], "pos": {}})
        seeded = len(hist.get("dates") or []) < 2
        if seeded:
            seeded_any = True
            print(f"  [{tf}] seeding history with {TIMEFRAMES[tf]['backfill']} past bars…")
            hist = backfill(series[tf], closes[tf], tf, TIMEFRAMES[tf]["backfill"])
        dates, pos = hist.get("dates", []), hist.get("pos", {})
        if not dates or dates[-1] != today:
            dates.append(today)
            for k in pos:
                pos[k].append(None)
        slot = len(dates) - 1
        prev = {}
        for d in allrows:                       # benchmarks get history too, to overlay
            arr = pos.setdefault(d["sym"], [None] * len(dates))
            while len(arr) < len(dates):
                arr.append(None)
            for j in range(slot - 1, -1, -1):
                if arr[j] is not None:
                    prev[d["sym"]] = arr[j]
                    break
            arr[slot] = d["pos"]
        if len(dates) > HISTORY_DAYS:
            cut = len(dates) - HISTORY_DAYS
            dates, pos = dates[cut:], {k: v[cut:] for k, v in pos.items()}
        pos = {k: v for k, v in pos.items() if any(x is not None for x in v)}
        for d in allrows:
            p = prev.get(d["sym"])
            d["prev"] = round(p, 1) if p is not None else None

        # ---- alerts ---------------------------------------------------------
        alerts = []
        for d in r:
            p, q = d["pos"], d.get("prev")
            if q is None:
                continue
            if p <= BOTTOM_ZONE < q:
                kind = "entered bottom zone"
            elif p < 0 <= q:
                kind = "broke below the lower band"
            else:
                continue
            alerts.append({"sym": d["sym"], "name": d["name"], "pos": p, "prev": q,
                           "r": d["r"], "dir": d["dir"], "kind": kind})
        alerts.sort(key=lambda a: a["pos"])
        all_alerts[tf] = alerts

        # ---- write ----------------------------------------------------------
        positions = sorted(d["pos"] for d in r)
        dip = [d for d in r if d["r"] >= 0.70 and d["slope"] > 0 and d["pos"] <= 25]
        payload = {
            "timeframe": tf,
            "timeframe_name": TIMEFRAMES[tf]["name"],
            "asof": today,
            "generated": now,
            "length": LENGTH,
            "devs": DEVS,
            "source": "yahoo",
            "repo": os.environ.get("GITHUB_REPOSITORY", ""),
            "stats": {
                "total": len(r),
                "below": sum(1 for d in r if d["pos"] < 0),
                "band": sum(1 for d in r if -ON_BAND <= d["pos"] <= ON_BAND),
                "bottom": sum(1 for d in r if d["pos"] <= BOTTOM_ZONE),
                "dip": len(dip),
                "median": round(positions[len(positions) // 2], 1) if positions else 0,
                "sp500": sum(1 for d in r if d["sp500"]),
            },
            "agg": aggregates(r),
            "benchmarks": bench_rows,
            "sector_etf": {k: v[0] for k, v in SECTOR_ETF.items()},
            "rows": r,
        }
        dump(os.path.join(outdir, f"latest-{tf}.json"), payload)
        dump(hpath, {"dates": dates, "pos": pos})

        sdir = os.path.join(outdir, "series", tf)
        shutil.rmtree(sdir, ignore_errors=True)
        os.makedirs(sdir, exist_ok=True)
        buckets = {}
        for sym, ser in series[tf].items():
            buckets.setdefault(bucket_of(sym), {})[sym] = ser
        for b, obj in buckets.items():
            dump(os.path.join(sdir, f"{b}.json"), obj, quiet=True)
        print(f"  [{tf}] {len(r)} rows · {len(buckets)} series files · {len(alerts)} alerts")

    dump(os.path.join(outdir, "alerts.json"),
         {"asof": today, "generated": now, "seeded": seeded_any,
          "default_timeframe": DEFAULT_TF, "alerts": all_alerts})
    dump(os.path.join(outdir, "meta.json"),
         {"timeframes": [{"id": t, "name": TIMEFRAMES[t]["name"]} for t in timeframes],
          "default": DEFAULT_TF if DEFAULT_TF in timeframes else timeframes[0],
          "generated": now})


def dump(path, obj, quiet=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    if not quiet:
        print(f"  wrote {os.path.relpath(path, ROOT)}  {os.path.getsize(path) / 1024:.0f} KB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeframes", default=os.environ.get("SCAN_TIMEFRAMES", "1d,1wk,1mo"))
    ap.add_argument("--out", default=DATA)
    a = ap.parse_args()
    tfs = tuple(t.strip() for t in a.timeframes.split(",") if t.strip() in TIMEFRAMES)
    run(a.limit, tfs or ("1mo",), a.out)

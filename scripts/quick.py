#!/usr/bin/env python3
"""
Quick intraday refresh — the 15-minute update.

Instead of re-downloading ten years of history for 1,300+ stocks, this pulls the
CURRENT quote for every symbol (~70 batched requests), grafts it onto the data
the site already published, recomputes every channel, and republishes.

  1. Fetch the live site's own data files (latest/series/meta — they're public).
  2. Fetch current prices via the batched spark endpoint (20 symbols/request).
  3. Update the live bar of each timeframe's series (close, clamp high/low,
     roll a new bar if a new day/week/month has started).
  4. Re-run the identical linreg/zone/%R math on the updated closes.
  5. Write data/ for the deploy step. Nothing is committed, no alerts fire —
     the 3×/day full scans keep doing that.

Exit codes: 0 = published data written · 3 = site not reachable yet (first run
of a fresh repo — the workflow just skips the deploy) · 2 = too few quotes.

Local test:  QUICK_BASE=http://localhost:8765 python3 scripts/quick.py
"""
import csv
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan  # the same math, one source of truth

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

repo = os.environ.get("GITHUB_REPOSITORY", "")
if os.environ.get("QUICK_BASE"):
    BASE = os.environ["QUICK_BASE"].rstrip("/")
elif "/" in repo:
    owner, name = repo.split("/", 1)
    BASE = f"https://{owner}.github.io/{name}"
else:
    sys.exit("set QUICK_BASE or GITHUB_REPOSITORY")

BUCKETS = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + ["_"]


def get_json(path):
    try:
        return scan.fetch(f"{BASE}/data/{path}", timeout=30, tries=2)
    except Exception:  # noqa: BLE001
        return None


def quotes_for(ysyms):
    """{yahoo_symbol: live price} via spark, 20 per request."""
    out = {}

    def batch(chunk):
        url = ("https://query1.finance.yahoo.com/v7/finance/spark?symbols="
               + ",".join(chunk) + "&range=1d&interval=1d")
        try:
            res = (scan.fetch(url).get("spark") or {}).get("result") or []
        except Exception:  # noqa: BLE001
            return {}
        got = {}
        for item in res:
            r = (item.get("response") or [None])[0]
            p = ((r or {}).get("meta") or {}).get("regularMarketPrice")
            if item.get("symbol") and isinstance(p, (int, float)):
                got[item["symbol"]] = float(p)
        return got

    chunks = [ysyms[i:i + 20] for i in range(0, len(ysyms), 20)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(batch, chunks):
            out.update(res)
    return out


def label_today(tf, today):
    if tf == "1d":
        return today.isoformat()
    if tf == "1wk":
        y, w, _ = today.isocalendar()
        return dt.date.fromisocalendar(y, w, 1).isoformat()
    return f"{today.year:04d}-{today.month:02d}"


def refresh_row(d, ser, price):
    """Graft the live price onto the published series, redo the math in place."""
    m = scan.linreg(ser["c"])
    if not m:
        return False
    old_price = d.get("price")
    d.update(pos=m["pos"], r=m["r"], slope=m["slope"], price=m["price"],
             lower=m["lower"], mid=m["mid"], upper=m["upper"], swings=m["swings"],
             zone=scan.zone(m["pos"]),
             dir="Uptrend" if m["slope"] > 0 else ("Downtrend" if m["slope"] < 0 else "Flat"),
             strength=scan.strength(m["r"]))
    c = ser["c"]
    d["chg"] = round((c[-1] / c[-2] - 1) * 100, 2) if len(c) >= 2 and c[-2] else None
    ser["wr"] = scan.williams_r(ser["h"], ser["l"], ser["c"])
    d["wr"] = ser["wr"][-1]
    # 52-week high carried from the full scan; only the "at a new high" case moves
    if d.get("hi52") is not None and old_price:
        peak = old_price / (1 + d["hi52"] / 100) if d["hi52"] else old_price
        peak = max(peak, price)
        d["hi52"] = round(min(0.0, (price / peak - 1) * 100), 1)
    return True


def main():
    meta = get_json("meta.json")
    if not meta or not meta.get("timeframes"):
        print("published site not reachable — run the full scan first")
        sys.exit(3)
    tfs = [t["id"] for t in meta["timeframes"]]

    latest, series = {}, {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        lat = {tf: ex.submit(get_json, f"latest-{tf}.json") for tf in tfs}
        ser = {(tf, b): ex.submit(get_json, f"series/{tf}/{b}.json")
               for tf in tfs for b in BUCKETS}
    for tf in tfs:
        latest[tf] = lat[tf].result()
        if not latest[tf]:
            print(f"could not fetch latest-{tf}.json")
            sys.exit(3)
        series[tf] = {}
        for b in BUCKETS:
            obj = ser[(tf, b)].result()
            if obj:
                series[tf].update(obj)

    # display symbol -> yahoo symbol, from the committed universe file
    y_of = {}
    with open(os.path.join(DATA, "universe.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            y_of[row["symbol"]] = row["yahoo"]

    syms = set()
    for tf in tfs:
        for d in latest[tf]["rows"] + latest[tf].get("benchmarks", []):
            syms.add(y_of.get(d["sym"], d["sym"]))
    q = quotes_for(sorted(syms))
    print(f"quotes: {len(q)}/{len(syms)}")
    if len(q) < 0.9 * len(syms):
        print("too few quotes — refusing to publish a half-updated site")
        sys.exit(2)

    today = dt.datetime.now(dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=-4))).date()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for tf in tfs:
        lab = label_today(tf, today)
        updated = 0
        for d in latest[tf]["rows"] + latest[tf].get("benchmarks", []):
            s = series[tf].get(d["sym"])
            price = q.get(y_of.get(d["sym"], d["sym"]))
            if not s or price is None or not s.get("c"):
                continue
            if s["t"][-1] != lab and today.weekday() < 5:
                for k in ("t", "o", "h", "l", "c"):
                    s[k] = s[k][1:] + [lab if k == "t" else round(price, 2)]
            else:
                s["c"][-1] = round(price, 2)
                s["h"][-1] = round(max(s["h"][-1], price), 2)
                s["l"][-1] = round(min(s["l"][-1], price), 2)
            if refresh_row(d, s, price):
                updated += 1

        rows = sorted(latest[tf]["rows"], key=lambda d: d["pos"])
        for i, d in enumerate(rows, 1):
            d["rank"] = i
        positions = sorted(d["pos"] for d in rows)
        dip = [d for d in rows if d["r"] >= 0.70 and d["slope"] > 0 and d["pos"] <= 25]
        latest[tf].update(
            rows=rows, asof=today.isoformat(), generated=now, mode="quick",
            agg=scan.aggregates(rows),
            stats={
                "total": len(rows),
                "below": sum(1 for d in rows if d["pos"] < 0),
                "band": sum(1 for d in rows if -scan.ON_BAND <= d["pos"] <= scan.ON_BAND),
                "bottom": sum(1 for d in rows if d["pos"] <= scan.BOTTOM_ZONE),
                "dip": len(dip),
                "median": round(positions[len(positions) // 2], 1) if positions else 0,
                "sp500": sum(1 for d in rows if d.get("sp500")),
            })
        scan.dump(os.path.join(DATA, f"latest-{tf}.json"), latest[tf])

        buckets = {}
        for sym, sobj in series[tf].items():
            buckets.setdefault(scan.bucket_of(sym), {})[sym] = sobj
        sdir = os.path.join(DATA, "series", tf)
        os.makedirs(sdir, exist_ok=True)
        for b, obj in buckets.items():
            scan.dump(os.path.join(sdir, f"{b}.json"), obj, quiet=True)
        print(f"  [{tf}] refreshed {updated} rows")

        # keep the published site complete: pass history through unchanged
        h = get_json(f"history-{tf}.json")
        if h:
            scan.dump(os.path.join(DATA, f"history-{tf}.json"), h, quiet=True)

    a = get_json("alerts.json")
    scan.dump(os.path.join(DATA, "alerts.json"), a or {"alerts": {}}, quiet=True)
    meta["generated"] = now
    scan.dump(os.path.join(DATA, "meta.json"), meta)
    print("quick refresh complete")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"{time.time() - t0:.0f}s")

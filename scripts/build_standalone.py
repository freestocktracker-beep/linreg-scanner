#!/usr/bin/env python3
"""
Bake site/index.html + everything under data/ into one self-contained HTML file.

Useful for looking at a scan without deploying, or for keeping a dated snapshot
next to the old spreadsheets. The hosted site does not use this.

Usage:  python3 scripts/build_standalone.py [output.html] [--timeframes 1mo]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

ap = argparse.ArgumentParser()
ap.add_argument("out", nargs="?")
ap.add_argument("--timeframes", default=None, help="comma list; default = whatever the scan produced")
a = ap.parse_args()

meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
tfs = [t.strip() for t in a.timeframes.split(",")] if a.timeframes else [t["id"] for t in meta["timeframes"]]
meta["timeframes"] = [t for t in meta["timeframes"] if t["id"] in tfs]
if meta["default"] not in tfs:
    meta["default"] = tfs[-1]

blob = {"meta": meta}
for tf in tfs:
    blob[f"latest-{tf}"] = json.load(open(os.path.join(DATA, f"latest-{tf}.json"), encoding="utf-8"))
    hp = os.path.join(DATA, f"history-{tf}.json")
    blob[f"history-{tf}"] = json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else None
    sdir = os.path.join(DATA, "series", tf)
    for fn in sorted(os.listdir(sdir)):
        blob[f"series/{tf}/{fn[:-5]}"] = json.load(open(os.path.join(sdir, fn), encoding="utf-8"))

html = open(os.path.join(ROOT, "site", "index.html"), encoding="utf-8").read()
payload = json.dumps(blob, separators=(",", ":")).replace("</", "<\\/")   # don't end the tag early
marker = '<script>\n"use strict";'
if marker not in html:
    sys.exit("could not find the main script tag in site/index.html")
html = html.replace(marker, '<script id="baked-data">window.__DATA__=' + payload + ";</script>\n" + marker, 1)
asof = blob[f"latest-{tfs[0]}"]["asof"]
html = html.replace("<title>LinReg Channel Scanner</title>",
                    f"<title>LinReg Channel Scanner — {asof}</title>", 1)

out = a.out or os.path.join(ROOT, f"LinReg_Scanner_{asof}.html")
open(out, "w", encoding="utf-8").write(html)
print("wrote %s  (%.1f MB, timeframes: %s)" % (out, os.path.getsize(out) / 1e6, ",".join(tfs)))

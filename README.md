# LinReg Channel Scanner

> Warm cream-and-charcoal theme with light and dark modes, serif display type, monospaced
> data, and a single terracotta accent. Data colours are semantic and never share duty with
> the chrome: blue = bottom of channel, red = top, green/red = bar direction, violet =
> events, amber = dividends.

A self-refreshing website that ranks ~1,300 US stocks by where they sit inside their
**linear-regression channel** — on the **daily, weekly and monthly** timeframes.
Same construction as TradingView's *Linear Regression Channel* at length 100 with 2
standard deviations. Stocks sitting on or below the bottom band sort to the top.

Everything runs on free GitHub infrastructure: a scheduled Action re-runs the scan
three times each weekday, republishes the site, and opens an issue (which GitHub
emails you) when something new drops into the bottom of its channel. No server, no
API key, no browser automation.

---

## Setting it up (about 5 minutes)

**1. Create the repository.**
On [github.com/new](https://github.com/new), name it `linreg-scanner`, choose
**Public** (required for free GitHub Pages), and create it. Leave it empty — no
README, no .gitignore.

**2. Upload these files.**
On the empty repo page click **uploading an existing file**, then drag in the
*contents* of this folder (not the folder itself). Commit.

<details>
<summary>Or from a terminal</summary>

```bash
cd linreg-scanner
git init && git branch -M main
git add . && git commit -m "initial"
git remote add origin https://github.com/YOUR-USERNAME/linreg-scanner.git
git push -u origin main
```
</details>

**3. Turn on Pages.**
**Settings → Pages → Build and deployment → Source: GitHub Actions.** That's the
only setting to change; don't pick a branch.

**4. Run it once by hand.**
**Actions → Scan and publish → Run workflow.** Takes about three minutes — it fetches
every stock, its dividends and its next earnings date, and seeds the position history.
(Uploading the files kicks off a run automatically. If that one failed because Pages
wasn't switched on yet, this is the re-run that fixes it.)

**5. Open your site.**
`https://YOUR-USERNAME.github.io/linreg-scanner/`

From here it refreshes on its own. Bookmark it.

---

## Using the site

- **New to this? Click "How to read"** in the header (or the **?** on any chart) for a
  plain-English walkthrough with a diagram of the channel. Every metric label, stat
  tile, and column header also carries a small **ⓘ** — hover it for a one-paragraph
  explanation written for a non-technical reader.

- **The market ticker** across the top scrolls SPY, QQQ, DIA, IWM and all eleven sectors —
  each chip shows the scanned price and its move, tinted by where that index sits in its
  own channel. It pauses when you hover, respects reduced-motion settings, and **clicking
  any chip** opens that ETF's own chart; from a sector's chart, "Show <sector> stocks"
  drills into its constituents.
- **✦ Forecast** on any chart continues the fitted trend forward as a dashed line with a
  proper statistical cone around it (a 95% prediction interval that widens with distance),
  plus a short generated outlook in plain English — the setup, the trend-continuation
  target over a natural horizon, the range, and the risks (earnings distance, sector
  standing). It's arithmetic from past prices, clearly labelled as such — the toggle
  remembers its state. There is no live AI call: the site is a static page with no server,
  so the "AI" is the same regression the channel is built on, projected honestly.
- **Stat tiles are filter buttons.** Clicking one applies its filter and the tile fills in;
  clicking it again clears. Because the table is sorted by channel position, a filter can
  leave the same names on top — so the active dropdown, the count and the tile all light up,
  and a ✕ Clear chip appears.
- **Daily / Weekly / Monthly** switch at the top right re-scopes everything — table,
  stats, charts. It's also inside the chart popup, so you can flip a stock between
  timeframes without closing it. The site remembers which one you were on.
- **A Chg column** shows each stock's move over its current bar (day, week, or month to
  date), and a **Signals** filter finds oversold (%R ≤ −80), overbought, or
  earnings-within-7-days names in one click.
- **Filters survive a reload**, and a ✕ Clear chip appears whenever any filter is active.
- **Candles or line** toggle in the chart popup, also remembered. A steady readout line
  above the chart — TradingView style — shows the hovered bar's date, O/H/L/C, change,
  channel position and %R, so your eye never has to chase a tooltip. The last close rides
  the price axis as a colored tag.
- **The chart moves.** Drag to pan, scroll to zoom (or the − / + buttons), range presets
  (1Y / 5Y on monthly, 1M / 3M on daily), double-click or **All** for the full window.
  There's always empty room to the right of the newest bar so the channel projects
  forward into it.
- **Bands are drawn as real reference lines** — red upper, blue lower, labelled with
  their prices — rather than the edges of a shaded area.
- **Events on the chart**: gold diamonds mark ex-dividend dates, and the next scheduled
  earnings report gets a dashed marker out in the projection space. Only the *upcoming*
  earnings date is available from a free source, so past reports aren't marked.
- **Days till earnings** has its own box in the stat panel, counting from today rather
  than from the last scan, with the date underneath. It turns amber inside seven days.
  The date also rides along in the CSV export, so you can sort a shortlist by it.
- **Williams %R (14)** runs underneath, sharing the same x window and crosshair: 0 is the
  top of the recent range, −100 the bottom, with the −20 / −80 bands shaded.
- **★ Favorites** — click the star on any row, then the **★ Favorites** button (or the
  Favorites tile) to see just those. Saved in your browser, and the **Alerts** button
  turns them into the config for email alerts.
- **Next › / ‹** in the chart popup walks the list you're currently looking at — filter
  down to "bottom zone + uptrend", open the first one, then arrow through them. The
  **←** and **→** keys do the same.
- **Benchmarks.** Every stat sits above a reference: the sector median, the share of the
  sector that's rising, the whole universe's median position. Below them, SPY, QQQ and
  the stock's own sector SPDR are run through the identical channel maths and reported in
  plain language — "near its floor", "around its trend line", "above its ceiling" — plus
  how far each is trading from its own regression line. One sentence up top says how the
  stock stands against its sector. The exact channel percentage is still there in each
  card's tooltip.
- **Colour means one thing.** Channel position uses a single diverging scale everywhere —
  deep blue at or below the lower band, neutral mid-channel, red at or above the upper
  band. The band tiles carry the same rails: blue for support, grey for the regression
  line, red for resistance. Green and red arrows are reserved for trend direction, and
  the zone is always spelled out in words too.
- **"On the lower band (±5%)"** is the tightest position filter — price within five points
  either side of the band, i.e. sitting right on it rather than merely in the lower 15%.
  It has its own stat tile and its own zone name throughout. The upper band has the
  matching ±5% option.
- **"Pullback in an uptrend"** applies position ≤ 25% + uptrend + R ≥ 0.70 in one click.
- **Export CSV** downloads exactly the rows you're looking at, for the timeframe you're on.
- Deep links work — `…/#MCD` opens straight to that stock.
- **Keyboard**: `/` jumps to search, `1`/`2`/`3` switch timeframe, and with a chart open
  `←`/`→` walk the list, `f` favorites, `c` flips candles/line, `Esc` closes.

## How it refreshes

| When | What runs |
|---|---|
| Every 15 min, market hours Mon–Fri | **Quick refresh** — live quotes grafted onto the last full scan (~70 requests, ~1 min), site republished. No commits, no alerts. |
| 14:00, 18:00, 21:00 UTC, Mon–Fri | Full scan, all three timeframes → history committed, alerts fire |
| 1st of the month, 08:30 UTC | Ticker universe rebuilt (index membership, market caps) |
| Any time | **Actions → Run workflow** for a manual refresh |

An open browser tab notices each refresh by itself: the page polls a ~200-byte
timestamp every 3 minutes and re-renders in place when it moves — filters, sort
and scroll survive. The quick refresh needs the site to exist, so it politely
skips until the first full scan has published.

Those UTC times are roughly 10am / 2pm / 5pm New York in summer, 9am / 1pm / 4pm in
winter — GitHub cron doesn't follow daylight saving. Edit the `cron:` lines in
`.github/workflows/scan.yml` to change the cadence. To scan fewer timeframes, set the
repository variable `SCAN_TIMEFRAMES` to e.g. `1wk,1mo`.

Because the newest bar is live, channel positions move during the session — most on the
daily channel, least on the monthly one.

## Alerts

After each run, any stock that *newly* crosses into the bottom 15% of its channel — or
breaks below the lower band — is collected into a GitHub issue titled "N stocks hit the
bottom of the channel". GitHub emails you about issues in your own repository, so
there's nothing else to configure.

Narrow what you hear about in **`config.json`**:

```json
{ "alerts": { "mode": "watchlist", "watchlist": ["MCD", "TSCO"],
              "timeframes": ["1mo"],
              "uptrend_only": true, "min_r": 0.7, "max_per_run": 25 } }
```

- `mode` — `"all"` for every stock, `"watchlist"` for just the symbols you list
- `timeframes` — which channels to watch. `["1mo"]` is the quiet default; adding
  `"1d"` will alert you many times more often
- `uptrend_only` — ignore stocks whose regression slope is negative
- `min_r` — minimum |Pearson R|, so choppy names stay quiet

The site's **Alerts** button generates this JSON from your starred stocks and current
timeframe, with a copy button and a link straight to the file on GitHub.

If you'd rather have a plain SMTP email, add
[`dawidd6/action-send-mail`](https://github.com/dawidd6/action-send-mail) as a step
after the notify step and feed it the same `data/alerts.json`.

## What's in here

```
scripts/scan.py              the scan: fetch, resample, fit the channels, write the JSON
scripts/universe.py          rebuilds data/universe.csv (S&P 500 + every US stock over $5B)
scripts/build_standalone.py  bakes a dated one-file HTML snapshot, no server needed
site/index.html              the whole website, one self-contained file
config.json                  alert settings
data/universe.csv            the ticker list                       (committed)
data/history-TF.json         channel position over time            (committed, accumulates)
data/latest-TF.json          ranked rows + stats per timeframe     (rebuilt each run)
data/series/TF/X.json        last 100 OHLC bars, bucketed by first letter
```

Only the universe and the position history live in git — everything else is rebuilt on
each run and published straight to Pages, which keeps the repository small.

Run it locally the same way the Action does:

```bash
python3 scripts/universe.py               # optional, refresh the ticker list
python3 scripts/scan.py                   # ~3 min for all three timeframes
python3 scripts/scan.py --limit 100       # or a quick subset while developing

mkdir -p _site && cp -r site/. _site/ && cp -r data _site/data
cd _site && python3 -m http.server 8000   # then open localhost:8000
```

`python3 scripts/build_standalone.py` writes one HTML file with everything baked in —
handy for a dated snapshot you can open without a server.

## Method

For each stock and each timeframe, a least-squares line is fitted to the last 100 bars'
closes. The channel is that line ± 2 × the standard deviation of the residuals.
**Position in channel** = `(price − lower) / (upper − lower) × 100`, so 0% is the lower
band and 100% the upper; negative means price has broken beneath the channel.
Zones are named from that position: below −5% is *below the lower band*, −5% to +5% is
**on the lower band**, up to 15% *near the bottom*, then lower third / mid-channel /
upper third, with the same ±5% treatment at the top.
**Swings** counts how often price travelled from the top zone (≥80%) to the bottom zone
(≤20%) within the window — a rough read on whether the channel has actually been
respected. Stocks without enough bars for a timeframe are left out of it; those under a
full 100-bar window are flagged `short`.

**Williams %R (14)** = `(highest high − close) / (highest high − lowest low) × −100` over
the last 14 bars of the timeframe you're on. It's computed server-side across the full
history so the first bars on screen have proper lookback rather than starting blank.

SPY, QQQ, DIA, IWM and the eleven sector SPDRs go through the same maths on every
timeframe. They're kept out of the ranking and stored separately as benchmarks, so
"below its lower band" can always be read against what the market itself is doing.

**Events.** Ex-dividend dates come back on the same price request, so they cost nothing
and cover the full ten years. The next scheduled earnings date needs Yahoo's cookie +
crumb handshake, which the scan does once per run and then reuses; if it fails, earnings
markers are simply absent and everything else still works. Set the repository variable
`SCAN_EARNINGS` to `0` to skip that pass entirely. Historical earnings *release* dates
aren't offered by any free source the scan can reach, so past reports are deliberately
not marked rather than approximated from fiscal quarter ends.

The scan pulls **ten years of split-adjusted daily bars** per stock from Yahoo Finance
in a single request, then resamples them into weekly and monthly bars — first open, last
close, extreme high and low, which reproduces Yahoo's own weekly and monthly series
exactly and is what your charting platform does too. One request per stock instead of
three is also much gentler on the source.

Closes are split-adjusted and not dividend-adjusted, which is what TradingView charts by
default. Spin-offs are the one place providers disagree materially — RTX, DD, MMM, EXC,
FTV and similar will differ between data sources.

## Troubleshooting

**"Scheduled workflows were disabled."** GitHub turns off cron in repositories with no
human activity for 60 days and emails you first — click the re-enable button in the
Actions tab. Any commit of your own resets the clock.

**The data commit fails with a permissions error.** Settings → Actions → General →
Workflow permissions → **Read and write permissions**.

**A run publishes nothing.** The scan aborts on purpose if fewer than 80% of symbols
return data, rather than publish a half-empty table. Re-run it; Yahoo occasionally
rate-limits.

**The site says "No scan data yet".** Pages deployed before the first scan finished —
run the workflow once and reload.

**A number disagrees with your TradingView chart.** Check whether the symbol has had a
spin-off (see Method), and that your chart is on the same timeframe with length 100 and
2 standard deviations.

---

Not investment advice. This is a mechanical indicator snapshot for research — it says
nothing about whether a business is cheap, sound, or worth owning.

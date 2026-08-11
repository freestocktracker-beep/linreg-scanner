# Deploying this — the 5-minute version

Everything in this folder is ready to go. Three settings and one button.

---

## 1. Create the repository

[github.com/new](https://github.com/new) → name it **`linreg-scanner`** → **Public**
(required for free GitHub Pages) → **Create repository**. Leave every "initialize with"
box unchecked.

## 2. Put these files in it

**Drag and drop:** on the empty repo page click **uploading an existing file**, open this
folder, select all 12 items *inside* it (not the folder itself) and drop them in.
Commit at the bottom of the page.

> ⚠️ Check that `.github/workflows/` made it up — some browsers skip dot-folders on
> drag-and-drop. After committing you should see a `.github` folder in the file list.
> If it's missing, use the terminal method below, or create the files by hand with
> **Add file → Create new file** and paste the path `.github/workflows/scan.yml`.

**Or from a terminal** (more reliable, needs git installed):

```bash
cd "path/to/linreg-scanner"
git init -b main
git add .
git commit -m "LinReg channel scanner"
git remote add origin https://github.com/YOUR-USERNAME/linreg-scanner.git
git push -u origin main
```

## 3. Turn on Pages

**Settings → Pages → Build and deployment → Source: GitHub Actions.**
That's the only setting to change — don't pick a branch.

> Uploading the files starts a workflow run automatically. If Pages wasn't on yet, that
> run fails at the deploy step. Harmless — step 4 is the re-run that succeeds.

## 4. Run it once

**Actions → Scan and publish → Run workflow.** Takes about three minutes: it downloads
ten years of history for ~1,360 symbols, fetches earnings dates, seeds the position
history, and publishes.

## 5. Open your site

`https://YOUR-USERNAME.github.io/linreg-scanner/`

From here it runs itself: a quick refresh every 15 minutes during market hours, a full
scan three times a day, and a universe rebuild monthly.

---

## Checking it worked

- **Actions tab** — "Scan and publish" green, then "Quick refresh" firing every 15 min
  during market hours.
- **The site header** should say "updated … (2m ago)" and tick over on its own.
- **A commit** from `linreg-scanner` adding `data/history-*.json`.

## If something goes wrong

| Symptom | Fix |
|---|---|
| Deploy step fails, "Pages not enabled" | Step 3, then re-run the workflow |
| Commit step fails, permission denied | Settings → Actions → General → Workflow permissions → **Read and write** |
| Site says "No scan data yet" | The first full scan hasn't finished — wait, or re-run it |
| "Quick refresh" logs *site not deployed yet* | Expected before the first full scan; it skips instead of failing |
| Scheduled runs stop after ~60 days idle | GitHub disables cron on quiet repos and emails you — click re-enable |
| A run fails with lots of Yahoo errors | Rate limiting. Re-run; if it persists, drop the quick refresh to every 30 min |

## Turning things down

- **Fewer quick refreshes:** edit the cron in `.github/workflows/quick.yml`
  (`*/15` → `*/30`), or delete the file to stop them entirely.
- **Alert volume:** `config.json` — `mode`, `timeframes`, `min_r`.
- **Smaller universe:** repository variable `MIN_MARKET_CAP` (default `5e9`).

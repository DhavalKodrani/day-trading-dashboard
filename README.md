# Day Trading Dashboard

A single-page stock dashboard that surfaces **bullish SMA crossovers** — stocks where the
**9-day simple moving average crossed above the 20-day simple moving average on the most recent
trading day** (a classic "golden cross" day-trading signal).

**Live site:** https://dhavalkodrani.github.io/day-trading-dashboard/

## How it works

A browser page can't scan thousands of tickers itself (no market-data feed, and the symbol
directories don't allow cross-origin requests), so the work is split:

```
GitHub Actions (weekday, after US close)
  └─ screener.py
       ├─ builds the full US-listed universe (~10k+)  ← NASDAQ Trader → SEC EDGAR → fallback
       ├─ downloads daily OHLCV via yfinance (batched)
       ├─ computes SMA-9 & SMA-20, finds today's bullish crossovers
       └─ writes signals.json  ──commit──▶  GitHub Pages rebuilds  ──▶  index.html renders it
```

- **`screener.py`** — the scanner. Universe sources are tried in order (NASDAQ Trader is usually
  blocked from cloud IPs, so SEC EDGAR's ~11k `company_tickers.json` is the workhorse). It keeps
  only stocks whose 9-day SMA sat at/below the 20-day SMA on the prior bar and moved above it on
  the latest session, drops stale/zero-price data, then records each match's last three trading
  days (date, close, volume) and a short-term trend flag.
- **`.github/workflows/scan.yml`** — runs the scanner at **21:30 UTC on weekdays** (after the US
  close year-round), plus a manual **Run workflow** button, and commits `signals.json`.
- **`index.html`** — loads `signals.json` and renders a sortable table. Until the first scan runs,
  it falls back to a built-in deterministic sample so the layout is always demonstrable.

## Dashboard features

- **Crossover filter** — only stocks that crossed up on the latest session.
- **Last three trading days** — date, current volume, and the last three closing prices per stock.
- **Trend arrow** — green ▲ when the short-term (SMA-9) slope is up, red ▼ when it turns down.
- **Sortable columns** — click any header to sort ascending/descending.
- **Data-source badge** — shows whether the page is on the live daily scan or the sample fallback.

## Run the scan yourself

```bash
pip install -r requirements.txt
python screener.py                 # full universe -> signals.json
python screener.py --limit 500     # quick test on the first 500 symbols
python screener.py --min-price 1 --min-avg-volume 500000   # optional liquidity filter
```

## Notes

- Prices come from Yahoo Finance via `yfinance`; a full-universe run takes a while and some thin
  or delisted symbols return no data (logged and skipped).
- This is a technical screen for **educational purposes — not financial advice.**

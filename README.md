# Day Trading Dashboard

A single-page stock dashboard that surfaces **bullish SMA crossovers** — stocks where the
**9-day simple moving average crossed above the 20-day simple moving average today** (a classic
"golden cross" day-trading signal).

## Features

- **Crossover filter** — only lists stocks whose SMA-9 was at/below SMA-20 yesterday and moved
  above it today.
- **Last three trading days** — each row shows the latest date, current volume, and closing
  prices for the last three sessions.
- **Trend arrow** — green ▲ when short-term momentum (SMA-9 slope) is up, red ▼ when it turns down.
- **Sortable columns** — click any column header to sort ascending/descending.
- **Zero dependencies** — one self-contained `index.html`; all indicators (SMA-9, SMA-20, the
  crossover test, trend, close/volume) are computed in the browser.

## Run it

Open `index.html` in any browser, or view the hosted version via GitHub Pages once enabled
(Settings → Pages → deploy from `main`).

## Using live data

The dataset is a deterministic sample so the demo is reproducible. To go live, replace
`buildSeries()` in `index.html` so it returns real daily closes/volumes from a market-data API
(e.g. Alpha Vantage, Finnhub, Polygon). The crossover filter and rendering logic are unchanged.

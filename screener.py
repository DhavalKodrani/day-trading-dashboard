#!/usr/bin/env python3
"""
Day Trading Dashboard - SMA crossover screener.

Scans the full US-listed universe (~10k+ symbols) once per run and finds the
stocks where the 9-day simple moving average crossed ABOVE the 20-day simple
moving average on the most recent trading day (a bullish "golden cross").

For each match it records the last three trading days (date, close, volume) and
a short-term trend flag, then writes signals.json for the dashboard to render.

Universe sources are tried in order (same approach as Stock_squeeze_screener):
  1. NASDAQ Trader symbol directory  (often blocked from cloud IPs)
  2. SEC EDGAR company_tickers.json   (reliable everywhere, ~11k names)
  3. tickers_fallback.txt             (last-resort local list)

This is a technical screen for educational purposes. Not financial advice.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

# --------------------------------------------------------------------------- #
# Configuration (tweak freely; CLI flags override the common ones)
# --------------------------------------------------------------------------- #
CONFIG = {
    "fast_ma": 9,
    "slow_ma": 20,
    "trend_lookback": 3,          # bars used to judge the up/down arrow
    "history_period": "3mo",      # enough daily bars for a 20-day SMA + prior day
    "interval": "1d",
    "batch_size": 120,            # tickers per yfinance download call
    "max_retries": 3,
    "retry_backoff_seconds": 5,
    "min_price": 0.0,             # 0 = keep the full universe (no liquidity filter)
    "min_avg_volume": 0,          # 0 = off
    "universe": {
        "nasdaq_listed_url": "https://ftp.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "other_listed_url": "https://ftp.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
        "sec_company_tickers_url": "https://www.sec.gov/files/company_tickers.json",
        "sec_user_agent": "DayTradingDashboard dhavalmountlaurel@gmail.com",
        "fallback_file": "tickers_fallback.txt",
        "exclude_symbols_with_chars": [".", "$", "+", "^", "="],  # warrants/units/rights
    },
    "output_path": "signals.json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("screener")


# --------------------------------------------------------------------------- #
# Universe building
# --------------------------------------------------------------------------- #
def _fetch_from_nasdaq_trader(u: dict) -> Dict[str, str]:
    names: Dict[str, str] = {}
    nasdaq = pd.read_csv(u["nasdaq_listed_url"], sep="|")
    other = pd.read_csv(u["other_listed_url"], sep="|")
    nasdaq = nasdaq[nasdaq["Symbol"].notna()]
    if "Test Issue" in nasdaq.columns:
        nasdaq = nasdaq[nasdaq["Test Issue"] != "Y"]
    for _, r in nasdaq.iterrows():
        names[str(r["Symbol"]).upper()] = str(r.get("Security Name", "")).strip()
    sym_col = "ACT Symbol" if "ACT Symbol" in other.columns else "Symbol"
    other = other[other[sym_col].notna()]
    if "Test Issue" in other.columns:
        other = other[other["Test Issue"] != "Y"]
    for _, r in other.iterrows():
        names[str(r[sym_col]).upper()] = str(r.get("Security Name", "")).strip()
    log.info("Fetched %d symbols from NASDAQ Trader.", len(names))
    return names


def _fetch_from_sec(u: dict) -> Dict[str, str]:
    headers = {"User-Agent": u["sec_user_agent"]}
    resp = requests.get(u["sec_company_tickers_url"], headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    names: Dict[str, str] = {}
    for entry in data.values():
        t = entry.get("ticker")
        if t:
            names[str(t).upper()] = str(entry.get("title", "")).strip().title()
    log.info("Fetched %d symbols from SEC EDGAR.", len(names))
    return names


def _fetch_from_fallback(u: dict) -> Dict[str, str]:
    names: Dict[str, str] = {}
    with open(u["fallback_file"], encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                names[s.upper()] = ""
    log.info("Loaded %d symbols from fallback file.", len(names))
    return names


def build_universe(cfg: dict, limit: Optional[int]) -> Dict[str, str]:
    u = cfg["universe"]
    names: Dict[str, str] = {}
    for label, fn in [
        ("NASDAQ Trader", lambda: _fetch_from_nasdaq_trader(u)),
        ("SEC EDGAR", lambda: _fetch_from_sec(u)),
        ("fallback file", lambda: _fetch_from_fallback(u)),
    ]:
        try:
            names = fn()
            if names:
                break
        except Exception as e:  # noqa: BLE001
            log.warning("Universe source '%s' failed (%s). Trying next.", label, e)

    bad = u["exclude_symbols_with_chars"]
    cleaned = {
        sym: nm for sym, nm in names.items()
        if sym and not any(c in sym for c in bad)
    }
    ordered = dict(sorted(cleaned.items()))
    if limit:
        ordered = dict(list(ordered.items())[:limit])
    log.info("UNIVERSE_TOTAL: %d", len(ordered))
    return ordered


# --------------------------------------------------------------------------- #
# Indicator + evaluation
# --------------------------------------------------------------------------- #
def evaluate(df: pd.DataFrame, cfg: dict) -> Optional[dict]:
    """Return a signal dict if SMA-fast crossed above SMA-slow on the last bar."""
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Close"])
    slow, fast = cfg["slow_ma"], cfg["fast_ma"]
    if len(df) < slow + 2:
        return None

    close = df["Close"].astype(float)
    vol = df["Volume"].astype(float) if "Volume" in df else pd.Series(0, index=df.index)
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    if pd.isna(ma_fast.iloc[-1]) or pd.isna(ma_slow.iloc[-1]) or pd.isna(ma_slow.iloc[-2]):
        return None

    # Bullish crossover on the latest bar: below/at yesterday, above today.
    crossed = ma_fast.iloc[-2] <= ma_slow.iloc[-2] and ma_fast.iloc[-1] > ma_slow.iloc[-1]
    if not crossed:
        return None

    if cfg["min_price"] and close.iloc[-1] < cfg["min_price"]:
        return None
    if cfg["min_avg_volume"] and vol.tail(20).mean() < cfg["min_avg_volume"]:
        return None

    last3 = df.tail(3)
    d = [ts.strftime("%Y-%m-%d") for ts in last3.index]
    c = [round(float(x), 2) for x in last3["Close"].tolist()]
    v = [int(x) for x in last3["Volume"].tolist()] if "Volume" in last3 else [0, 0, 0]

    if c[-1] <= 0 or any(pd.isna(x) for x in last3["Close"].tolist()):
        return None  # drop bad/thin data (zero or missing closes)

    # Trend = actual price momentum across the three shown sessions (today vs two
    # days ago), NOT the SMA-9 slope (which is up by construction after a cross).
    chg = round((c[-1] / c[-3] - 1) * 100, 2) if c[-3] else 0.0
    trend_up = c[-1] >= c[-3]

    return {
        "date": d[-1], "d1": d[-2], "d2": d[-3],
        "close0": c[-1], "close1": c[-2], "close2": c[-3],
        "vol0": v[-1], "vol1": v[-2], "vol2": v[-3],
        "volume": v[-1],   # kept for backward-compat (today's volume)
        "up": trend_up,
        "chg": chg,        # % change over the 3-day window
    }


def extract_ticker_frame(data: pd.DataFrame, ticker: str, single: bool) -> Optional[pd.DataFrame]:
    try:
        if single:
            return data
        if isinstance(data.columns, pd.MultiIndex):
            if ticker not in data.columns.get_level_values(0):
                return None
            return data[ticker]
        return data
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Main scan
# --------------------------------------------------------------------------- #
def run(cfg: dict, limit: Optional[int]) -> dict:
    if yf is None:
        raise RuntimeError("yfinance not installed. Run: pip install -r requirements.txt")

    universe = build_universe(cfg, limit)
    symbols = list(universe.keys())
    total = len(symbols)
    signals: List[dict] = []
    scanned = 0

    for i in range(0, total, cfg["batch_size"]):
        batch = symbols[i:i + cfg["batch_size"]]
        data = None
        for attempt in range(1, cfg["max_retries"] + 1):
            try:
                data = yf.download(
                    batch, period=cfg["history_period"], interval=cfg["interval"],
                    group_by="ticker", threads=True, progress=False, auto_adjust=True,
                )
                break
            except Exception as e:  # noqa: BLE001
                log.warning("Batch %d download failed (%d/%d): %s",
                            i // cfg["batch_size"], attempt, cfg["max_retries"], e)
                time.sleep(cfg["retry_backoff_seconds"] * attempt)
        if data is None or data.empty:
            continue

        single = len(batch) == 1
        for t in batch:
            df = extract_ticker_frame(data, t, single)
            sig = evaluate(df, cfg)
            if sig:
                sig["sym"] = t
                sig["name"] = universe.get(t, "")
                signals.append(sig)
        scanned += len(batch)
        log.info("Scanned %d/%d  |  crossovers so far: %d", scanned, total, len(signals))

    # "Crossed today" must mean the latest session: keep only signals whose last
    # bar is the most recent date seen across the scan (drops stale/thin tickers
    # whose newest bar lags a day or more).
    if signals:
        latest = max(s["date"] for s in signals)
        stale = [s for s in signals if s["date"] != latest]
        if stale:
            log.info("Dropping %d stale signal(s) not on the latest session %s.", len(stale), latest)
        signals = [s for s in signals if s["date"] == latest]
        as_of = latest
    else:
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    signals.sort(key=lambda s: s["volume"], reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of,
        "universe_scanned": total,
        "signals": signals,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="9/20 SMA crossover screener for the Day Trading Dashboard.")
    p.add_argument("--limit", type=int, default=None,
                   help="Only scan the first N symbols (for quick testing).")
    p.add_argument("--min-price", type=float, default=None, help="Override min price filter.")
    p.add_argument("--min-avg-volume", type=float, default=None, help="Override min avg volume filter.")
    p.add_argument("--out", default=None, help="Output path (default signals.json).")
    args = p.parse_args()

    cfg = dict(CONFIG)
    if args.min_price is not None:
        cfg["min_price"] = args.min_price
    if args.min_avg_volume is not None:
        cfg["min_avg_volume"] = args.min_avg_volume
    out_path = args.out or cfg["output_path"]

    result = run(cfg, args.limit)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s: %d crossover(s) from %d symbols scanned.",
             out_path, len(result["signals"]), result["universe_scanned"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

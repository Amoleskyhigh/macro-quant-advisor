#!/usr/bin/env python3
"""
Daily market data fetcher for macro-quant-advisor dashboard.
Writes data.json used by index.html.

Data sources:
  - yfinance : VIX, TNX, DXY, SPY, Copper (no key needed)
  - CNN API  : Fear & Greed (no key needed)
  - multpl   : Shiller CAPE (scraped, no key needed)
  - FRED API : HY OAS (free key -> set FRED_API_KEY secret in GitHub)
"""

import json, os, sys, datetime, requests
import yfinance as yf

FRED_KEY = os.environ.get("FRED_API_KEY", "")


def yf_closes(ticker, period="90d"):
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return None, []
        c = hist["Close"].tolist()
        return c[-1], c
    except Exception as e:
        print(f"[yf] {ticker}: {e}", file=sys.stderr)
        return None, []


def moving_avg(lst, n):
    if not lst:
        return None
    return sum(lst[-n:]) / min(n, len(lst))


def fear_greed():
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12
        )
        return int(r.json()["fear_and_greed"]["score"])
    except Exception as e:
        print(f"[F&G] {e}", file=sys.stderr)
        return None


def shiller_pe():
    import re
    try:
        r = requests.get(
            "https://www.multpl.com/shiller-pe",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=12
        )
        m = re.search(r'id="current-value"[^>]*>\s*([\d.]+)', r.text)
        if m:
            return float(m.group(1))
    except Exception as e:
        print(f"[Shiller] {e}", file=sys.stderr)
    return None


def fred_value(series_id):
    if not FRED_KEY:
        print(f"[FRED] No FRED_API_KEY, skipping {series_id}", file=sys.stderr)
        return None
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={FRED_KEY}"
            f"&sort_order=desc&limit=5&file_type=json"
        )
        obs = [o for o in requests.get(url, timeout=12).json().get("observations", [])
               if o["value"] != "."]
        return float(obs[0]["value"]) if obs else None
    except Exception as e:
        print(f"[FRED] {series_id}: {e}", file=sys.stderr)
        return None


def spx_breadth():
    try:
        import pandas as pd
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"}
        )
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"[breadth] Downloading {len(tickers)} tickers ...", file=sys.stderr)
        data = yf.download(
            tickers, period="80d", auto_adjust=True,
            progress=False, threads=True
        )["Close"]
        above, total = 0, 0
        for t in tickers:
            if t not in data.columns:
                continue
            s = data[t].dropna()
            if len(s) < 50:
                continue
            if s.iloc[-1] > s.rolling(50).mean().iloc[-1]:
                above += 1
            total += 1
        result = round(above / total * 100, 2) if total else None
        print(f"[breadth] {above}/{total} = {result}%", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[breadth] {e}", file=sys.stderr)
        return None


def main():
    print("Fetching market data ...", file=sys.stderr)

    vix_cur,    vix_h    = yf_closes("^VIX",      "30d")
    tnx_cur,    tnx_h    = yf_closes("^TNX",      "60d")
    dxy_cur,    dxy_h    = yf_closes("DX-Y.NYB",  "60d")
    spy_cur,    spy_h    = yf_closes("SPY",        "300d")
    copper_cur, copper_h = yf_closes("HG=F",       "30d")

    fg      = fear_greed()
    cape    = shiller_pe()
    hy_oas  = fred_value("BAMLH0A0HYM2")
    breadth = spx_breadth()

    def r(v, d=2):
        return round(v, d) if v is not None else None

    result = {
        "timestamp":  datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vix":        r(vix_cur),
        "fearGreed":  fg,
        "shillerPE":  r(cape, 2),
        "hyOAS":      round(hy_oas) if hy_oas else None,
        "breadth":    breadth,
        "tnx":        r(tnx_cur, 3),
        "tnxMA20":    r(moving_avg(tnx_h, 20), 3),
        "dxy":        r(dxy_cur, 2),
        "dxyMA20":    r(moving_avg(dxy_h, 20), 2),
        "spyPrice":   r(spy_cur, 2),
        "spyMA200":   r(moving_avg(spy_h, 200), 2),
        "copper":     r(copper_cur, 3),
        "copperMA3":  r(moving_avg(copper_h, 3), 3),
        "alloc":      {"cash": 18, "qqq": 24, "smh": 31, "boxx": 27, "qld": 0},
    }

    out = json.dumps(result, indent=2, ensure_ascii=False)
    with open("data.json", "w") as f:
        f.write(out)
    print(out)
    print("\n✅ data.json written.", file=sys.stderr)


if __name__ == "__main__":
    main()

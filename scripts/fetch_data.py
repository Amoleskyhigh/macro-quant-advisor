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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


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
    """Fetch CNN Fear & Greed Index with multiple fallback approaches."""
    endpoints = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/chart",
    ]
    for url in endpoints:
        try:
            r = requests.get(
                url,
                headers={**HEADERS, "Referer": "https://www.cnn.com/markets/fear-and-greed"},
                timeout=15
            )
            if r.status_code != 200:
                print(f"[F&G] HTTP {r.status_code} from {url}", file=sys.stderr)
                continue
            data = r.json()
            # Handle different response structures
            fg = data.get("fear_and_greed", data)
            score = fg.get("score") or fg.get("current_score") or fg.get("value")
            if score is not None:
                return int(float(score))
        except Exception as e:
            print(f"[F&G] {url}: {e}", file=sys.stderr)
    return None


def shiller_pe():
    """Scrape Shiller PE from multpl.com with multiple regex patterns."""
    import re
    try:
        r = requests.get(
            "https://www.multpl.com/shiller-pe",
            headers=HEADERS,
            timeout=15
        )
        if r.status_code != 200:
            print(f"[Shiller] HTTP {r.status_code}", file=sys.stderr)
            return None

        # Try multiple patterns for robustness
        patterns = [
            r'id=["\']current-value["\'][^>]*>\s*\$?\s*([\d]+\.[\d]+)',
            r'id=["\']current-value["\'][^>]*>\s*\$?\s*([\d]+)',
            r'class=["\']current["\'][^>]*>[\s\S]{0,50}?([\d]{2}\.[\d]+)',
            r'"current_value"\s*:\s*"?([\d]+\.[\d]+)"?',
        ]
        for pat in patterns:
            m = re.search(pat, r.text, re.IGNORECASE)
            if m:
                val = float(m.group(1).replace(",", ""))
                if 5 < val < 200:
                    print(f"[Shiller] {val}", file=sys.stderr)
                    return val

        # Last resort: find any 2-digit.2-digit number near "shiller" or "cape"
        m = re.search(
            r'(?:shiller|cape|p/e)[^<]{0,300}?([\d]{2}\.[\d]{1,2})',
            r.text, re.IGNORECASE | re.DOTALL
        )
        if m:
            val = float(m.group(1))
            if 5 < val < 200:
                print(f"[Shiller] fallback: {val}", file=sys.stderr)
                return val

        print("[Shiller] No match found", file=sys.stderr)
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


# Representative ~60 S&P 500 stocks (replaces slow full-500 download)
SPX_SAMPLE = [
    # Mega cap tech
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AVGO", "AMD",
    "ORCL", "ADBE", "CRM", "QCOM", "TXN", "INTC",
    # Finance
    "JPM", "BAC", "WFC", "GS", "BLK", "V", "MA", "AXP",
    # Healthcare
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "AMGN",
    # Consumer
    "HD", "COST", "WMT", "MCD", "SBUX", "NKE", "TGT",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Industrial
    "CAT", "BA", "GE", "HON", "RTX", "UPS", "DE",
    # Communication / Media
    "DIS", "NFLX", "T", "VZ", "CMCSA",
    # Utilities / Real estate
    "NEE", "SO", "DUK", "AMT", "PLD",
]


def spx_breadth():
    """% of representative S&P 500 stocks above their 50-day MA."""
    try:
        print(f"[breadth] Downloading {len(SPX_SAMPLE)} stocks ...", file=sys.stderr)
        data = yf.download(
            SPX_SAMPLE, period="80d", auto_adjust=True,
            progress=False, threads=True
        )["Close"]
        above, total = 0, 0
        for t in SPX_SAMPLE:
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

"""Four facts about Kalshi that cost this lab real money to learn, as code.

    python kalshi_facts.py KXBTC15M-26JUL301945-45      # what a ticker means
    python kalshi_facts.py KXWTI15M                     # what settles a series

No key needed. Everything here is from the public API.

1. The time in a ticker is New York time, not UTC.
   KXBTC15M-26JUL301945-45 reads 19:45; the exchange's close_time says
   23:45Z. In December the gap is five hours. Parse with America/New_York
   or, better, use close_time from the API.
2. The settlement source is per series, and for commodities it is a Pyth
   INDEX feed, not the spot feed most people watch.
3. Fee type is per series. About 130 series charge makers; the rest do not.
   KXATPMATCH charges, KXATPCHALLENGERMATCH does not. Never match a prefix.
4. There is free history back to late 2025: markets, trade tape, one-minute
   candles. There is no historical order book.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "https://api.elections.kalshi.com/trade-api/v2"
HIST = "https://external-api.kalshi.com/trade-api/v2"
NY = ZoneInfo("America/New_York")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kalshi-facts/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def ticker_time(ticker):
    """The datetime embedded in a ticker, as an aware New York datetime, or None.
    Format: <SERIES>-<YY><MON><DD><HHMM>[-<strike>]"""
    m = re.match(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})", ticker)
    if not m:
        return None
    yy, mon, dd, hh, mm = m.groups()
    return datetime.strptime(f"20{yy}{mon}{dd}{hh}{mm}", "%Y%b%d%H%M").replace(tzinfo=NY)


def series_of(ticker):
    return ticker.split("-")[0]


def describe_ticker(ticker):
    tt = ticker_time(ticker)
    m = get(f"{BASE}/markets/{ticker}").get("market", {})
    close = m.get("close_time")
    print(f"ticker          {ticker}")
    if tt:
        print(f"ticker time     {tt.strftime('%Y-%m-%d %H:%M')} New York  = {tt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%MZ')}")
    print(f"api close_time  {close}   <- use this one")
    print(f"result          {m.get('result') or 'open'}   exchange_index {m.get('exchange_index')}")
    describe_series(series_of(ticker))


def describe_series(series):
    s = get(f"{BASE}/series/{series}").get("series", {})
    fee = s.get("fee_type")
    print(f"series          {series}: {s.get('title')}")
    print(f"fee_type        {fee}   -> makers {'PAY a quarter of the taker rate (a flat 1c per fill at one contract)' if fee == 'quadratic_with_maker_fees' else 'pay nothing'}")
    for src in s.get("settlement_sources", []) or []:
        print(f"settles on      {src.get('name')}   {src.get('url')}")


def history_reach(series):
    """How far back the free history goes for a series (walks the cursor)."""
    cur, n, oldest = "", 0, None
    while True:
        d = get(f"{HIST}/historical/markets?series_ticker={series}&limit=1000" + (f"&cursor={cur}" if cur else ""))
        ms = d.get("markets", [])
        n += len(ms)
        if ms:
            oldest = ms[-1].get("close_time")
        cur = d.get("cursor")
        if not cur or not ms:
            break
    print(f"free history    {n} markets, oldest close {oldest}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    arg = sys.argv[1]
    if "-" in arg and re.search(r"-\d{2}[A-Z]{3}\d{2}", arg):
        describe_ticker(arg)
    else:
        describe_series(arg)
        if "--history" in sys.argv:
            history_reach(arg)

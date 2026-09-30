"""📜 histfill — backfill Kalshi's own history, free (2026-08-20).

A r/Kalshi reader (thainfamouzjay) pointed at endpoints we had missed.
They are real, unauthenticated, and they reach back roughly six months —
far past our own recorder, which starts 2026-07-21:

    GET external-api.kalshi.com/trade-api/v2/historical/markets
        ?series_ticker=KXBTC15M&limit=1000        (cursor paginated)
    GET .../historical/trades?ticker=<FULL_MARKET_TICKER>&limit=1000
    GET .../historical/markets/<TICKER>/candlesticks
        ?start_ts=&end_ts=&period_interval=1      (1-minute OHLC + OI)

KXBTC15M alone returns 12,000+ markets back to 2026-02-13. That is five
extra months of settled outcomes to calibrate against, and it costs a
few minutes of polling rather than five months of waiting.

WHAT THIS DOES NOT GET: L2 depth is not served historically, and the
candles are 1-minute where our own recorder keeps 1-second top of book.
Those two, plus our fill ledger, are the only parts of our archive that
are genuinely unrecoverable — see the corrected note in archiver.py.

OWN DATABASE FILE, deliberately. Bulk backfill writes tens of thousands
of rows in a burst; kalshi_log.db is 8GB shared by ~40 live processes
and we spent today digging out of exactly that kind of contention. This
touches none of it. Read-only against the exchange, no keys, no trading.

USAGE
    python histfill.py markets                  # all series below
    python histfill.py markets KXBTC15M         # just one
    python histfill.py candles KXBTC15M 300     # candles, newest 300 mkts
    python histfill.py trades  KXBTC15M 300     # tape, newest 300 markets
    python histfill.py status                   # what we hold
"""
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DB_PATH = "hist.db"
BASE = "https://external-api.kalshi.com/trade-api/v2"
SERIES = ("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M",
          "KXWTI15M", "KXBTCD", "KXETHD")
PAUSE = 0.45          # be a good citizen; this is a free gift from Kalshi
MAX_PAGES = 200


def log(m):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')}Z] {m}",
          flush=True)


def get(path, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(
                BASE + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return None


def init_db():
    db = sqlite3.connect(DB_PATH, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("""CREATE TABLE IF NOT EXISTS hist_markets (
        ticker TEXT PRIMARY KEY, series TEXT, open_time TEXT,
        close_time TEXT, result TEXT, strike REAL, volume REAL,
        open_interest REAL, raw TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_hm ON "
               "hist_markets(series, close_time)")
    db.execute("""CREATE TABLE IF NOT EXISTS hist_trades (
        trade_id TEXT PRIMARY KEY, ticker TEXT, ts TEXT, yes_price REAL,
        no_price REAL, count REAL, taker_side TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_ht ON hist_trades(ticker, ts)")
    db.execute("""CREATE TABLE IF NOT EXISTS hist_candles (
        ticker TEXT, end_ts INTEGER, open REAL, high REAL, low REAL,
        close REAL, mean REAL, open_interest REAL, volume REAL,
        PRIMARY KEY (ticker, end_ts))""")
    db.execute("""CREATE TABLE IF NOT EXISTS hist_done (
        ticker TEXT, kind TEXT, ts TEXT, PRIMARY KEY (ticker, kind))""")
    db.commit()
    return db


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fill_markets(db, series):
    cur, added, pages = "", 0, 0
    while pages < MAX_PAGES:
        d = get(f"/historical/markets?series_ticker={series}&limit=1000"
                + (f"&cursor={cur}" if cur else ""))
        if not d:
            break
        ms = d.get("markets") or []
        if not ms:
            break
        pages += 1
        rows = []
        for m in ms:
            st = m.get("custom_strike") or {}
            # the historical API suffixes numerics: volume_fp,
            # open_interest_fp, *_dollars. Reading plain "volume" got
            # NULL for 472k rows before this was caught (2026-08-20).
            rows.append((
                m.get("ticker"), series, m.get("open_time"),
                m.get("close_time"), m.get("result"),
                f(m.get("floor_strike") or m.get("cap_strike")
                  or st.get("value")),
                f(m.get("volume_fp")), f(m.get("open_interest_fp")),
                json.dumps(m)))
        db.executemany(
            "INSERT OR REPLACE INTO hist_markets VALUES (?,?,?,?,?,?,?,?,?)",
            rows)
        db.commit()
        added += len(rows)
        cur = d.get("cursor") or ""
        log(f"   {series}: {added} markets so far (page {pages})")
        if not cur:
            break
        time.sleep(PAUSE)
    return added


def targets(db, series, limit):
    """Newest markets first, skipping ones already pulled."""
    return [r[0] for r in db.execute(
        "SELECT m.ticker FROM hist_markets m LEFT JOIN hist_done d "
        "ON d.ticker = m.ticker AND d.kind = ? WHERE m.series = ? "
        "AND d.ticker IS NULL ORDER BY m.close_time DESC LIMIT ?",
        (targets.kind, series, limit))]


def mark(db, ticker, kind):
    db.execute("INSERT OR REPLACE INTO hist_done VALUES (?,?,?)",
               (ticker, kind, datetime.now(timezone.utc).isoformat()))


def fill_trades(db, series, limit):
    targets.kind = "trades"
    tks, total = targets(db, series, limit), 0
    log(f"   {series}: {len(tks)} markets need the tape")
    for i, tk in enumerate(tks, 1):
        d = get(f"/historical/trades?ticker={tk}&limit=1000")
        rows = []
        for t in ((d or {}).get("trades") or []):
            rows.append((t.get("trade_id"), tk, t.get("created_time"),
                         f(t.get("yes_price_dollars")),
                         f(t.get("no_price_dollars")),
                         f(t.get("count_fp")), t.get("taker_book_side")))
        if rows:
            db.executemany("INSERT OR REPLACE INTO hist_trades "
                           "VALUES (?,?,?,?,?,?,?)", rows)
            total += len(rows)
        mark(db, tk, "trades")
        if i % 25 == 0:
            db.commit()
            log(f"   {series}: {i}/{len(tks)} markets, {total} trades")
        time.sleep(PAUSE)
    db.commit()
    return total


def fill_candles(db, series, limit):
    targets.kind = "candles"
    tks, total = targets(db, series, limit), 0
    log(f"   {series}: {len(tks)} markets need candles")
    for i, tk in enumerate(tks, 1):
        r = db.execute("SELECT open_time, close_time FROM hist_markets "
                       "WHERE ticker=?", (tk,)).fetchone()
        if not r or not r[1]:
            mark(db, tk, "candles")
            continue
        try:
            end = int(datetime.fromisoformat(
                str(r[1]).replace("Z", "+00:00")).timestamp())
            start = int(datetime.fromisoformat(
                str(r[0]).replace("Z", "+00:00")).timestamp()) if r[0] \
                else end - 3600
        except ValueError:
            mark(db, tk, "candles")
            continue
        d = get(f"/historical/markets/{tk}/candlesticks?start_ts={start}"
                f"&end_ts={end}&period_interval=1")
        rows = []
        for c in ((d or {}).get("candlesticks") or []):
            p = c.get("price") or {}
            rows.append((tk, c.get("end_period_ts"), f(p.get("open")),
                         f(p.get("high")), f(p.get("low")), f(p.get("close")),
                         f(p.get("mean")), f(c.get("open_interest")),
                         f(c.get("volume"))))
        if rows:
            db.executemany("INSERT OR REPLACE INTO hist_candles "
                           "VALUES (?,?,?,?,?,?,?,?,?)", rows)
            total += len(rows)
        mark(db, tk, "candles")
        if i % 25 == 0:
            db.commit()
            log(f"   {series}: {i}/{len(tks)} markets, {total} candles")
        time.sleep(PAUSE)
    db.commit()
    return total


def status(db):
    print("\n  series      markets   oldest close      settled   trades  candles")
    for s in SERIES:
        n, old, res = db.execute(
            "SELECT COUNT(*), MIN(close_time), SUM(result IN ('yes','no')) "
            "FROM hist_markets WHERE series=?", (s,)).fetchone()
        if not n:
            continue
        tr = db.execute("SELECT COUNT(*) FROM hist_trades WHERE ticker IN "
                        "(SELECT ticker FROM hist_markets WHERE series=?)",
                        (s,)).fetchone()[0]
        ca = db.execute("SELECT COUNT(*) FROM hist_candles WHERE ticker IN "
                        "(SELECT ticker FROM hist_markets WHERE series=?)",
                        (s,)).fetchone()[0]
        print("  %-11s %7d   %-16s %7s %8d %8d"
              % (s, n, (old or "")[:16], res or 0, tr, ca))
    print()


def main():
    db = init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status(db)
        return
    only = sys.argv[2] if len(sys.argv) > 2 else None
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    for s in ([only] if only else SERIES):
        if cmd == "markets":
            log(f"📜 {s}: markets")
            log(f"   {s}: +{fill_markets(db, s)} markets")
        elif cmd == "trades":
            log(f"📜 {s}: trades")
            log(f"   {s}: +{fill_trades(db, s, lim)} trades")
        elif cmd == "candles":
            log(f"📜 {s}: candles")
            log(f"   {s}: +{fill_candles(db, s, lim)} candles")
        else:
            print(__doc__)
            return
    status(db)


if __name__ == "__main__":
    main()

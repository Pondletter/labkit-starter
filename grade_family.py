#!/usr/bin/env python3
"""Grade "maker buys the favourite at 74-93c late" on a series from Kalshi's
free public history. Nothing is written to disk except a JSON summary; the
trade tape is held per market in memory and discarded. Volume floor and a
market cap protect the disk (the 2026-09-12 pull filled it).

usage: grade_family.py SERIES [--days 60] [--min-vol 500] [--max-mkts 400]
                       [--window-h 24]
cell:   prints in the last WINDOW hours where the favourite (side priced
        >50 at that print) trades at 74-93c and the TAKER is on the other
        side, i.e. a maker bought the favourite. P&L for that maker per
        contract: +(100-p) if the favourite settles, else -p.
mirror: same prints, taker bought the favourite (pays the taker fee)."""
import sys, json, math, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
import statistics as st

BASE = "https://api.elections.kalshi.com/trade-api/v2"
def get(path, params=None):
    q = ("?" + urllib.parse.urlencode(params, doseq=True)) if params else ""
    req = urllib.request.Request(BASE + path + q, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i == 3: raise
            time.sleep(1.5 * (i + 1))
def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
def taker_fee(p, n=1):
    return math.ceil(7 * p * (100 - p) / 10000 * n)

series = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ""
DAYS, MINVOL, MAXM, WH = arg("--days", 60), arg("--min-vol", 500), arg("--max-mkts", 400), arg("--window-h", 24.0)
SKIP = arg("--skip-days", 0)      # ignore the most recent SKIP days (to grade an earlier period)
BLO, BHI = arg("--band-lo", 74), arg("--band-hi", 93)   # favourite price band
ENDH = arg("--end-h", 0)          # exclude the last ENDH hours before close
TDIST = "--tdist" in sys.argv     # print where the cell's prints sit in time

def main():
    if not series:
        sys.exit(__doc__)
    hist = {}
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
    until = (datetime.now(timezone.utc) - timedelta(days=SKIP)).isoformat()
    mkts, cur = [], None
    while len(mkts) < MAXM:
        d = get("/markets", {"series_ticker": series, "status": "settled", "limit": 200, **({"cursor": cur} if cur else {})})
        ms = d.get("markets", [])
        for m in ms:
            # the list endpoint returns volume as null; the floor is applied to
            # the contracts actually seen in the market's trade tape instead
            if since <= m.get("close_time", "") <= until and m.get("result") in ("yes", "no"):
                mkts.append(m)
        cur = d.get("cursor")
        if not cur or not ms: break
        if ms and ms[-1].get("close_time", "") < since: break
    mkts = mkts[:MAXM]
    print(f"{series}: {len(mkts)} settled markets in the last {DAYS}d (floor {MINVOL} contracts applied per tape)", file=sys.stderr)

    cell, mirror, per_mkt, per_day, contracts = [], [], [], {}, 0
    for i, m in enumerate(mkts):
        tk, res = m["ticker"], m["result"]
        close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        start = close - timedelta(hours=WH)
        end = close - timedelta(hours=ENDH)
        trades, cur = [], None
        while True:
            d = get("/markets/trades", {"ticker": tk, "limit": 1000, **({"cursor": cur} if cur else {})})
            ts = d.get("trades", [])
            trades += ts
            cur = d.get("cursor")
            if not cur or not ts or len(trades) > 20000: break
        mk_c, mk_n = 0.0, 0
        def cnt(t): return float(t.get("count_fp") or t.get("count") or 0)
        def ypx(t):
            if t.get("yes_price_dollars") is not None: return int(round(float(t["yes_price_dollars"]) * 100))
            return int(t.get("yes_price") or 0)
        if sum(cnt(t) for t in trades) < MINVOL:
            continue                      # volume floor, measured on the tape
        for t in trades:
            try:
                at = datetime.fromisoformat(t["created_time"].replace("Z", "+00:00"))
            except Exception:
                continue
            if not (start <= at <= end): continue
            if TDIST:
                b = int((close - at).total_seconds() // 3600)
                hist[b] = hist.get(b, 0) + 1
            yp, n, taker = ypx(t), cnt(t), t.get("taker_side")
            if n <= 0 or taker not in ("yes", "no"): continue
            fav = "yes" if yp > 50 else "no"
            fp = yp if fav == "yes" else 100 - yp
            if not (BLO <= fp <= BHI): continue
            won = (res == fav)
            pnl_maker = (100 - fp) if won else -fp
            if taker != fav:            # taker sold the favourite -> maker BOUGHT it
                cell += [pnl_maker] * min(int(n), 200)
                mk_c += pnl_maker * n; mk_n += n; contracts += n
            else:                       # taker bought the favourite
                mirror += [pnl_maker - taker_fee(fp)] * min(int(n), 200)
        if mk_n:
            per_mkt.append(mk_c / mk_n)
            d = close.strftime("%Y-%m-%d"); per_day[d] = per_day.get(d, 0) + mk_c
        if i % 25 == 0: print(f"  ...{i}/{len(mkts)}", file=sys.stderr)

    def stats(v):
        if len(v) < 20: return None
        m = st.mean(v); sd = st.pstdev(v) or 1e-9
        return {"n": len(v), "mean": round(m, 2), "t": round(m / (sd / len(v) ** 0.5), 2)}
    out = {"series": series, "markets": len(mkts), "markets_with_cell": len(per_mkt),
           "window_h": WH, "end_h": ENDH, "days": DAYS, "skip_days": SKIP, "band": [BLO, BHI],
           "cell_prints_by_hours_before_close": dict(sorted(hist.items())) if TDIST else None, "contracts_in_cell": int(contracts),
           "maker_buys_fav_contract_wt": stats(cell), "market_level": stats(per_mkt),
           "mirror_taker_buys_fav": stats(mirror),
           "close_dates": len(per_day), "days_positive": sum(1 for v in per_day.values() if v > 0),
           "split": [round(st.mean(per_mkt[:len(per_mkt)//2]), 2), round(st.mean(per_mkt[len(per_mkt)//2:]), 2)] if len(per_mkt) >= 20 else None}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
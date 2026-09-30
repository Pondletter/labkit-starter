"""💸 Series-aware Kalshi fees — the single source of truth (2026-08-03).

WHY THIS EXISTS. On 2026-07-07 Kalshi introduced maker fees on a subset of
series, exposed as `fee_type` on GET /series/{ticker}:
    quadratic                 -> maker FREE   (10,600+ series, ~98.8%)
    quadratic_with_maker_fees -> maker pays ceil(0.0175*C*P*(1-P))  (~132)
Our 2026-08-02 correction observed $0.00 across 964 real maker fills and
concluded "maker fee is ZERO on Kalshi". The observation was right, the
conclusion over-generalized: every one of those fills was in a `quadratic`
series, while the maker-fee schedule had already existed for 26 days. Two
paper lanes were mispriced in opposite directions before this module:
    fed_watch  UNDER-charged (KXFED/KXCPI/KXPAYROLLS all charge makers;
               with ceil, 1-lot pays a flat 1c/fill at every price)
    mm_sports  OVER-charged (flat taker formula on a mixed universe)

THE PREFIX TRAP (verified live 2026-08-03): KXATPMATCH charges makers,
KXATPCHALLENGERMATCH does not. Both match 'KXATP%'. Resolve fee_type on the
EXACT series ticker, never a prefix.

Ground truth for any change here: `exchange_fills.fee_cents` — the exchange's
own charge per real fill. This module must reproduce those numbers.

Usage:
    import fees
    fees.taker_fee_cents(price)                    # any series
    fees.maker_fee_cents(db, ticker, price)        # series-aware, cached
Series types are cached in SQLite (`series_fees`) and refreshed after 24h;
unknown/unreachable series fall back to the verified 2026-08-03 snapshot
below, then to "quadratic" (maker free) — matching every live lane we run."""
import json
import math
import time
import urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2"
TAKER_COEFF = 7.0      # 0.07 in the codebase's integer-cent convention
MAKER_COEFF = 1.75     # 0.0175 — exactly 25% of taker
REFRESH_SECS = 86400

# verified live 2026-08-03 — offline fallback, NOT a substitute for the API
KNOWN = {
    "KXFED": "quadratic_with_maker_fees",
    "KXCPI": "quadratic_with_maker_fees",
    "KXPAYROLLS": "quadratic_with_maker_fees",
    "KXMLBGAME": "quadratic_with_maker_fees",
    "KXNBAGAME": "quadratic_with_maker_fees",
    "KXNFLGAME": "quadratic_with_maker_fees",
    "KXWTAMATCH": "quadratic_with_maker_fees",
    "KXATPMATCH": "quadratic_with_maker_fees",
    "KXBTC15M": "quadratic", "KXETH15M": "quadratic", "KXSOL15M": "quadratic",
    "KXXRP15M": "quadratic", "KXDOGE15M": "quadratic", "KXNEAR15M": "quadratic",
    "KXZEC15M": "quadratic", "KXHYPE15M": "quadratic", "KXBNB15M": "quadratic",
    "KXHIGHNY": "quadratic", "KXHIGHCHI": "quadratic",
    "KXCS2GAME": "quadratic", "KXCS2MAP": "quadratic",
    "KXVALORANTGAME": "quadratic", "KXVALORANTMAP": "quadratic",
    "KXDOTA2GAME": "quadratic", "KXDOTA2MAP": "quadratic",
    "KXLOLGAME": "quadratic", "KXLOLMAP": "quadratic",
    "KXATPCHALLENGERMATCH": "quadratic", "KXWTACHALLENGERMATCH": "quadratic",
    "KXITFMATCH": "quadratic", "KXITFWMATCH": "quadratic",
    "KXMLBRFI": "quadratic", "KXHUNDREDMATCH": "quadratic",
    "KXUFCFIGHT": "quadratic", "KXMLSGAME": "quadratic",
    "KXBTCD": "quadratic", "KXETHD": "quadratic", "KXSOLD": "quadratic",
    "KXINXU": "quadratic",
}


def series_of(ticker):
    """KXCS2MAP-26JUL241000BLAEAC-2-EAC -> KXCS2MAP. The series ticker is
    everything before the first '-'. EXACT match only after that — see the
    KXATPMATCH / KXATPCHALLENGERMATCH trap in the module docstring."""
    return ticker.split("-")[0] if ticker else ""


def _init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS series_fees (
        series TEXT PRIMARY KEY, fee_type TEXT, fee_multiplier REAL,
        fetched REAL)""")


def _fetch(series):
    req = urllib.request.Request(f"{BASE}/series/{series}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode())
    ser = d.get("series", d)
    return ser.get("fee_type") or "quadratic", ser.get("fee_multiplier", 1)


def fee_type(db, ticker):
    """(fee_type, fee_multiplier) for a ticker's series, cached 24h."""
    s = series_of(ticker)
    if not s:
        return "quadratic", 1
    _init(db)
    row = db.execute("SELECT fee_type, fee_multiplier, fetched FROM "
                     "series_fees WHERE series=?", (s,)).fetchone()
    if row and time.time() - (row[2] or 0) < REFRESH_SECS:
        return row[0], row[1] if row[1] is not None else 1
    try:
        ft, fm = _fetch(s)
        db.execute("INSERT INTO series_fees VALUES (?,?,?,?) "
                   "ON CONFLICT(series) DO UPDATE SET fee_type=excluded."
                   "fee_type, fee_multiplier=excluded.fee_multiplier, "
                   "fetched=excluded.fetched", (s, ft, fm, time.time()))
        db.commit()
        return ft, fm if fm is not None else 1
    except Exception:  # noqa: BLE001
        if row:                          # stale cache beats a guess
            return row[0], row[1] if row[1] is not None else 1
        return KNOWN.get(s, "quadratic"), 1


def taker_fee_cents(p, count=1, mult=1):
    """ceil(0.07 * C * P * (1-P)), in cents. mult=0 on ~10 fully-free series."""
    if not mult:
        return 0
    return math.ceil(mult * TAKER_COEFF * count * p * (100 - p) / 10000)


def maker_fee_cents(db, ticker, p, count=1):
    """0 on `quadratic` series (every live lane we run). On
    `quadratic_with_maker_fees`: ceil(0.0175*C*P*(1-P)) — which the ceil turns
    into a FLAT 1c/fill at 1 lot at every price. Against MAKER_UPLIFT=0.7c
    measured capture, 1-lot maker in these series is negative before edge."""
    ft, fm = fee_type(db, ticker)
    if ft != "quadratic_with_maker_fees" or not fm:
        return 0
    return math.ceil(fm * MAKER_COEFF * count * p * (100 - p) / 10000)


def maker_charged(db, ticker):
    """True if this ticker's series charges makers. Use as a seating guard."""
    return fee_type(db, ticker)[0] == "quadratic_with_maker_fees"


if __name__ == "__main__":
    # self-test: must reproduce the exchange's real charges
    for p in range(1, 100):
        assert maker_fee_cents.__defaults__  # keep linters quiet
    import sqlite3
    db = sqlite3.connect(":memory:")
    # quadratic -> 0 at every price (the 964 verified $0.00 maker fills)
    for p in range(1, 100):
        assert maker_fee_cents(db, "KXBTC15M-TEST", p) == 0
    # maker-fee series at 1 lot -> flat 1c at every price (ceil)
    for p in range(1, 100):
        assert maker_fee_cents(db, "KXFED-TEST", p) == 1, p
    # taker formula spot checks (the brief's table)
    assert taker_fee_cents(50) == 2       # $0.0175 -> ceil -> 2c? NO: 1.75 -> 2
    assert taker_fee_cents(95) == 1
    assert taker_fee_cents(50, count=100) == 175
    print("fees.py self-test OK")

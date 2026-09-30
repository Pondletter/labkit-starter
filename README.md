# Before you build a Kalshi bot: the starter

Four small tools from the Pondletter lab, free, no API key needed. They cover the things that cost the lab real money to learn before its first strategy ever traded. The full harness, the paper engine, the block machinery and the recorders, is at [pondletter.com/before-you-build](https://pondletter.com/before-you-build/).

Python 3.11 or newer. No dependencies beyond the standard library.

## kalshi_facts.py

What a ticker actually means and what settles a series.

```
python kalshi_facts.py KXBTC15M-26JUL301945-45
python kalshi_facts.py KXWTI15M --history
```

The time inside a ticker is New York time, not UTC, and the gap to the API's `close_time` is four hours in summer and five in winter. Commodity series settle on Pyth index feeds, not the spot feeds. Fee type is per exact series.

## fees.py

The fee schedule as code. `fee_type(db, ticker)` looks up and caches whether a series charges makers. `maker_fee_cents(db, ticker, price)` and `taker_fee_cents(price)` apply the exchange's formula including the rounding that makes a one-contract maker fill cost a flat cent on the series that charge.

```
python -c "import sqlite3, fees; db = sqlite3.connect('fees.db')
for s in ('KXBTC15M', 'KXATPMATCH', 'KXATPCHALLENGERMATCH'):
    print(s, fees.fee_type(db, s + '-X'), fees.maker_fee_cents(db, s + '-X', 80))"
```

## histfill.py

Backfills Kalshi's free history into SQLite: every market a series ever listed (back to late 2025), the trade tape per market, and one-minute candles with bid, ask, volume and open interest.

```
python histfill.py KXBTC15M
```

There is no historical order book. If you need depth, you have to record it yourself from the day you start.

## grade_family.py

Grades a series from the public trade tape at the honest unit: one number per market, split half by date, days positive. Use it to decide where to point a bot before you write it.

```
python grade_family.py KXBTC15M --days 14
```

## Why these four

Every one of them is a lesson from [the graveyard](https://pondletter.com/the-graveyard-forty-experiments-on-kalshi-and-the-one-that-survived/): about forty strategies tested on Kalshi with real money, almost all of which died, and the specific thing that killed each one. The lessons in order, free: [pondletter.com/before-you-build](https://pondletter.com/before-you-build/).

Nothing here is advice. It is the record.

## Building it with an AI assistant?

Paste `KALSHI-CONTEXT.md` into Claude, ChatGPT or Cursor before it writes a line, then ask it to check its code against every item. It is the traps above as facts a model can verify, with no strategy in it.

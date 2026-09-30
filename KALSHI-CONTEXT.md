# Kalshi context for your AI assistant

Paste this file into Claude, ChatGPT, Cursor or whatever writes your bot, before it
writes a line. Then ask it to check its own code against every item below. Each one
is something a model gets wrong by default, and each one cost the lab that published
this real money to learn. Everything here is a fact about the exchange or a measured
result, not a strategy. Sources: six months of live trading on Kalshi, every result
public at pondletter.com, sealed nightly.

## Time

- The datetime inside a Kalshi ticker is US Eastern (America/New_York), not UTC.
  `KXBTC15M-26JUL301945-45` reads 19:45 and closes at 23:45Z in summer, 00:45Z the
  next day in winter. Never parse the ticker for time. Use the market's `close_time`
  field, which is UTC.
- Some series carry a nominal `close_time` far past the real end. Mention markets
  close weeks after the speech; tournament-winner markets close weeks after the
  final. Use `expected_expiration_time`, an event start field, or the market's own
  activity, and expect settlement long before `close_time`.
- 15-minute markets settle every 15 minutes around the clock, about 96 a day per
  series.

## Fees

- Fees are set per series by the `fee_type` field, not per exchange. Read it for
  the exact series. Never infer it from a ticker prefix: `KXATPMATCH` charges
  makers, `KXATPCHALLENGERMATCH` does not, and both start the same way.
- `quadratic` (the default, roughly 13,000 series): takers pay
  `ceil(0.07 x contracts x P x (1 - P))` dollars, makers pay nothing.
- `quadratic_with_maker_fees` (about 130 series, the big sports and economics
  markets): takers pay the same, makers pay `ceil(0.0175 x contracts x P x (1 - P))`.
  Because of the ceiling, one contract pays a flat one cent at every price on these
  series. A quote that earns one or two cents hands most of it back.
- Prices in the API are `yes_bid_dollars` style strings and contract counts are
  `count_fp`. Account balance is reported in cents.

## Settlement

- The 15-minute Bitcoin market does not settle on the last trade or the chart. It
  resolves on the simple average of the 60 seconds of the CF Benchmarks BRTI index
  before close. By the final 30 seconds half of the settlement value is already
  fixed while the chart still moves.
- The 15-minute commodity series (gold, silver, WTI, natural gas and others) settle
  on Pyth index feeds, not the spot price your data vendor shows.
- The same real-world event settles differently on different venues. Kalshi and
  Polymarket resolved the same weather market to different outcomes in 19% of 640
  matched cases. A cross-venue "arbitrage" is not one unless the settlement source
  is identical.
- Read the market's `rules_primary` text. It says what the market actually settles
  on, and it is the only source that counts.

## Data

- Kalshi serves about six months of history free and without a key at
  `https://api.elections.kalshi.com/trade-api/v2`: `/markets` (settled and open),
  `/markets/trades?ticker=`, and one-minute candlesticks with bid and ask. The
  market list returns `volume` as null; measure volume from the trade tape.
- There is no historical order book anywhere. Depth exists only if you were
  recording it when it happened. Record top-of-book and depth from day one; it is
  the one thing you cannot get later, and it decides what size a strategy can ever
  run.
- The public API rate-limits bursts (HTTP 429). Page slowly and back off.

## What the record says about strategies

- Taking (crossing the spread) lost after fees on every strategy the lab ran. The
  spread on these books costs about 6 cents a fill; no edge the lab found was
  larger. Every strategy that survived rested orders.
- Win rate is not edge. Two bots with the same 84% win rate: the one that rested
  orders made money, the one that paid the spread lost 6 cents a fill.
- Prices are well calibrated above 90 cents and slightly generous to longshots
  below 30 cents (implied 15.6%, paid 14.2%). Favourites at 74 to 93 cents are
  underpriced on the public tape in several liquid families; whether a resting
  bid actually gets filled there is a separate question.
- Do not add take-profit or stop-loss rules. Replayed across 103,006 positions and
  17 exit rules, every rule lost to holding to settlement. The rule cuts about two
  winners for every loser it dodges.
- Do not buy the dip on a crashing favourite. 662 fills, minus 8.3 cents each. The
  panic price already knows.
- The edge the lab could find was about two cents a contract. So was the friction.
  Every attempt to add size turned the edge per contract negative, because the
  extra fills are the ones a faster maker did not want.

## Paper trading that does not lie

- A paper fill counts only when a real print arrives on your side of the book at
  or through your price. Marking a fill because the bid touched your level is
  fiction; the book does not offer that price on the way down.
- Even honest paper overstates live results. The lab's best paper strategy showed
  plus 1.87 cents a fill and lost money within 13 hours live, because a simulated
  counterparty has no reason to trade with you and the real one does.
- Test in fixed blocks: a set number of orders, a pass mark written down before the
  first one, graded once at the end. Never tune in the middle of a block.

## Engineering rules the lab enforces in code

- Fetch first, write second. Never hold a SQLite write lock across a network call.
  It starves every other process on the database.
- Register every order in your own database on its own connection before the
  next action, or cancel it. An order the exchange has and you do not is how money
  disappears.
- Run your stops (daily loss, lifetime loss, kill bar) every cycle, whether or not
  the last exchange sync succeeded.
- Reconcile from the exchange's fill records, never from your own ledger. The
  exchange is the truth.
- Carry the exchange's order identifiers on every cancel. A cancel without them can
  silently miss.
- Hash and publish your fill ledger nightly if you ever want a stranger to believe
  your results.

## What this file is not

It is not advice, it contains no quoting logic, and it will not find you an edge.
It will stop your assistant writing the bugs above into a bot that then trades
real money. The lessons behind each line are at pondletter.com/before-you-build.

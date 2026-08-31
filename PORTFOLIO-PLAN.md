# Portfolio dashboard

## Objective

Add a local, transaction-backed portfolio beside the research watchlist. The
portfolio must answer two different questions without rewriting history:

1. What did the investor own, when was it bought, what did it cost including
   fees, and what did the Graham screen say at that time?
2. What is the position worth now, how has its valuation and evidence changed,
   and which changes deserve review?

`tracked` remains a watchlist. Ownership is never a boolean on that table: it is
the net result of immutable buys and sells.

## Accounting model

- A portfolio has a name and base currency. Paper and live accounts can remain
  separate.
- A trade records CIK, ticker at execution, side, quantity, fill price, fees,
  currency, execution time, broker/account label, and an optional external ID.
- Quantities and money are stored as decimal strings; binary floats are not used
  for cost basis.
- Buy cost basis is `quantity * price + fees`.
- Sell proceeds are `quantity * price - fees`.
- Remaining cost basis and realised profit use FIFO lots. The UI also reports
  average cost per remaining share.
- Current market value is explicitly dated. A missing or stale quote remains
  unavailable rather than becoming zero.
- A quote older than the latest trade is retained as a clearly labelled reference
  value, but its price-dependent criterion changes are not presented as an exit
  signal or as post-purchase performance.
- Quotes disclose both the session that produced the price (pre-market, RTH, or
  after-hours) and the market state at fetch. Outside the provider's published
  pre/post windows the security is marked sleeping; an unsupported overnight
  price is never inferred from the previous RTH close.
- Non-USD trades stay separate until an explicit FX source exists.
- Bonds and crypto are current holdings, separate from the immutable stock trade
  ledger. Bond prices remain manual. Crypto markets are selected from Coinbase's
  public active-pair catalogue and valued from its live last-trade ticker; the
  saved quote is a disclosed fallback when refresh fails. Quantity and the saved
  price remain decimal text.
- Liquid cash is a persisted portfolio balance. An amount that has never been
  entered remains unknown, not zero, so the combined total and allocation do not
  overstate completeness.

## Decision evidence

Each trade stores an immutable copy of the dashboard row and its payload metadata:
dashboard generation time, engine version, quote time, filing dates, criteria,
alignment results, notes, assumptions, and provenance.

Two purchase views are retained:

- **Decision snapshot:** exactly what the screener displayed when the trade was
  entered.
- **Execution valuation:** P/E, P/E3, P/B, P/TBV, P/NCAV, recurring yield,
  all-capex-floor yield, maintenance≈D&A-estimate yield, and standard-FCF yield
  recomputed from the same filing evidence at the actual fill price. A definitive
  owner-earnings yield is withheld. Only price-dependent conclusions may change.

This distinction is necessary when the dashboard carries the prior regular close
but the broker fills in another session.

## Portfolio screen

The position table shows quantity, average cost including fees, current dated
price, cost basis, market value, unrealised P&L, portfolio weight, first/latest
trade dates, purchase-versus-current Graham fit, and purchase-versus-current
valuation multiples. Existing multi-column sorting semantics apply.

The top-level dashboard totals stocks, bonds, crypto, and liquid cash and shows
their allocation percentages. Its three tabs keep the full stock ledger in
**Stocks** and provide current-holding lists for **Bonds** and **Crypto**. A
missing stock quote or unentered cash balance withholds the combined total and
allocation percentages. Holdings can be added, updated, and removed; cash can be
entered or updated directly in the summary. While the page is open, crypto quotes
and the resulting allocation refresh every 30 seconds.

The position detail shows:

- every trade and fee;
- decision and execution snapshots for each buy lot;
- criterion changes by criterion number (1, 2, 3, 4, 5, and 7);
- price-only changes separately from filing/fundamental changes;
- source dates and engine versions, so a new filing and an engine correction are
  not mistaken for the same event.

No automatic `SELL` recommendation is produced. A valuation test changing from
PASS to FAIL is an **exit-review signal**, because Graham's entry tests alone do
not define a complete sell discipline.

## Workflow

- `Record trade` is available from the screener detail and portfolio screen.
- The API refreshes every eligible universe ticker hourly, including available
  pre/post bars, and atomically replaces one dashboard snapshot. Research and
  Portfolio both read that exact snapshot. A per-ticker provider failure retains
  the previous dated quote and is disclosed instead of clearing values.
- Required fields are portfolio, buy/sell, execution time, quantity, fill price,
  and fees. Current ticker and price may prefill but remain editable.
- Corrections delete and recreate a trade in the first release; later imports use
  broker execution IDs for idempotence.
- An IBKR Activity Statement/Flex CSV importer is preferred over screenshots for
  ongoing use because it carries authoritative execution IDs, times, quantities,
  prices, commissions, and later corporate actions.

## Delivery stages

1. SQLite ledger, immutable snapshots, FIFO calculations, CRUD API, portfolio
   summary/table/detail, and manual buy/sell entry.
2. Seed the current paper portfolio from the 41 verified executions.
3. IBKR CSV import with duplicate protection and a preview/reconciliation step.
4. Dividends, splits, transfers, multi-currency FX, daily equity history, and
   configurable review alerts.

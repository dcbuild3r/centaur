---
name: dune-analytics
description: Use the World Foundation Dune query catalog with the Dune CLI for onchain analysis.
---

# Dune Analytics

Use the `dune` CLI for read-only onchain analysis. The maintained query source
is [worldcoin-foundation/dune](https://github.com/worldcoin-foundation/dune).
The repository contains SQL snapshots and the canonical query IDs; the files
are not automatically synchronized with Dune.

## CLI capabilities

- `dune health` — read-only authentication/connectivity check.
- `dune query <query_id>` — fetch saved-query metadata, description, and
  parameter definitions.
- `dune execute <query_id> [--params '<json>']` — start an execution and return
  its execution ID.
- `dune status <execution_id>` — inspect execution state and queue position.
- `dune results <execution_id> [--limit N]` — fetch completed results; use
  `--json` when the rows need to be processed programmatically.
- `dune run <query_id> [--params '<json>'] [--timeout SECONDS] [--limit N]` —
  execute, poll, and display results in one command. The default timeout is
  300 seconds; this spends Dune credits.
- `dune cancel <execution_id>` — cancel a pending or running execution.
- `dune raw <endpoint> [-X METHOD] [-d '<json>']` — call another Dune API
  endpoint only when a purpose-built command is insufficient.

For an unfamiliar query, call `dune query` first. For expensive or long-lived
queries, prefer the materialized views documented in the repository README and
report the query ID, execution state, row count, and time range in the answer.
Never expose `DUNE_API_KEY` or include it in query text, output, or Slack.

## World Foundation query catalog

Use the saved IDs below rather than guessing from filenames. Query metadata and
SQL remain authoritative in the linked repository.

### WLD supply, emissions, and allocation

- `5714847` — WLD circulating-supply events (base event model).
- `6314397` — WLD circulating-supply events by day with metadata.
- `4173135` — current WLD circulating supply (live event model; not the daily
  materialized view).
- `4129347` — WLD circulating supply by day.
- `5961238` — WLD circulating supply by category and day.
- `6316021` — WLD allocated supply by category and day.
- `6313608` — ecosystem and network-operations tokens left.
- `3681469` — circulating-supply compensation for the 40-day TF sales lockup.
- `4150241` — WLD unlock schedule.
- `4150553` — Worldcoin community tokens emitted.
- `4151653` — Worldcoin operator rewards by day.
- `7573765` — referral rewards over time.
- `4150642` — Worldcoin user grants by day.
- `4150644` — first Worldcoin user grant time per address.

### Addresses, wallets, holders, and transfers

- `5715378` — current Worldcoin internal-address classifications (preferred;
  `4161913` is the deprecated predecessor).
- `4161913` — deprecated Worldcoin internal addresses.
- `4307219` — deployer addresses.
- `4129369` — WLD holders.
- `4129401` — current Worldchain WLD holders.
- `4151750` — WLD transfers.
- `4161932` — Worldcoin user-grant transfers.
- `4165680` — World App wallets.
- `4165749` — World App wallet creations.
- `4155156` — new Worldchain wallets.
- `4155565` — Worldchain token transfers.
- `4165745` — Worldchain Safes deployed.
- `4166235` — Worldchain bridge inflow assets.
- `4155474` — Worldchain bridgers.

### Worldchain activity and DEXs

- `4154712` — Worldchain active wallets (slow; approximately ten minutes on
  large ranges and approximate distinct counts).
- `4155732` — Worldchain DEX volume.
- `4154474` — Worldchain Worldcoin DEX volume.
- `4165872` — Worldchain Uniswap activity.
- `4673861` — daily balances for all Worldchain Uniswap pools.
- `4610512` — Worldchain Uniswap WLD pools.
- `4635191` — daily WLD Uniswap pool balances.
- `4634560` — daily WLD TVL in Worldchain DeFi.
- `4610228` — total WLD TVL in Worldchain DeFi (legacy).
- `4166291` — Worldchain WLD vault actions.
- `4166298` — historical Worldchain WLD vault deposits.
- `5298594` — Worldchain Uniswap TVL for the last 30 days.
- `6367355` — daily Worldchain prices.

### TVL, stablecoins, and Morpho

- `6554198` — Worldchain TVL by date, token, and address category.
- `6554457` — Worldchain TVL by token category and address category.
- `6587967` — Worldchain TVL by token/address category excluding internal
  holdings.
- `4715413` — Worldchain TVL by category and day (legacy).
- `6554711` — EURC adoption.
- `6554778` — wARS adoption.
- `5298889` — World Chain Morpho deposits by vault.
- `5340318` — World Chain Morpho borrow and collateral by market.
- `5353799` — World Chain Morpho collateral by asset.
- `5353810` — World Chain Morpho borrow by asset.
- `5353928` — World Chain Morpho TVL by asset and type.

## Materialized views

The repository README identifies these as the preferred daily sources:

- `dune.world.result_wld_circulating_supply_events` — source for query `5714847`.
- `dune.world.result_wld_circulating_supply_events_by_day_metadata` — source
  for most circulating-supply and allocation metrics; refreshes daily.
- `dune.world.result_worldchain_prices_daily` — daily Worldchain prices; vault
  tokens whose prices are mechanically derivable are intentionally excluded.
- `dune.world.result_worldchain_tvl_by_date_token_addresscategory` — daily
  Worldchain TVL by date/token/address category.

When answering a question, identify whether the result is live, daily
materialized, or a legacy query, and state that distinction. Do not silently
substitute a legacy query for a materialized view.

# Discovery: Commodity Futures (MCX) Support & Auto-Rollover

**Status:** Discovery only. No source under `src/` was modified.
**Scope of the planned feature:** Add historical OHLC fetching for **commodity futures** (GOLD, SILVER, CRUDEOIL, etc. on MCX) with **auto-rollover / contract-selection** logic (near-month, near-1, near+1, and a specific named month/year), each resolvable on its own thread. Equity/index F&O and commodity *options* are explicitly deferred (forward-compat notes only).
**Evidence base:** Source files under `src/zerodha_data_fetcher/` and the bundled instrument master `src/zerodha_data_fetcher/utils/data/Kite_Instrument_ID.csv` (86,684 data rows in this snapshot).

---

## 1. How the instrument master represents derivatives

### 1.1 CSV columns (exact header)

From `src/zerodha_data_fetcher/utils/data/Kite_Instrument_ID.csv` line 1:

```
instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
```

This is the raw Kite `https://api.kite.trade/instruments` dump (12 columns). Note the library only *renames/keeps* four of these downstream (see §2.3), but the full set is present on disk.

### 1.2 MCX commodity futures — real examples

Filtering `exchange == MCX`, `segment == MCX-FUT`, `instrument_type == FUT`:

```
109124103,426266,GOLD24AUGFUT,"GOLD",0,2024-08-05,0,1,1,FUT,MCX-FUT,MCX
109127687,426280,GOLD24OCTFUT,"GOLD",0,2024-10-04,0,1,1,FUT,MCX-FUT,MCX
109175815,426468,GOLD24DECFUT,"GOLD",0,2024-12-05,0,1,1,FUT,MCX-FUT,MCX
109760007,428750,GOLD25FEBFUT,"GOLD",0,2025-02-05,0,1,1,FUT,MCX-FUT,MCX
109570055,428008,CRUDEOIL24JULFUT,"CRUDEOIL",0,2024-07-19,0,1,1,FUT,MCX-FUT,MCX
109790471,428869,CRUDEOIL24AUGFUT,"CRUDEOIL",0,2024-08-19,0,1,1,FUT,MCX-FUT,MCX
109123847,426265,SILVER24SEPFUT,"SILVER",0,2024-09-05,0,1,1,FUT,MCX-FUT,MCX
```

Key observations, column by column:

| Field | Value for MCX futures | Notes for selection logic |
|---|---|---|
| `instrument_token` | e.g. `109124103` | The only thing the fetch path needs (see §3). |
| `tradingsymbol` | `GOLD24AUGFUT` | Pattern: `<NAME><YY><MON>FUT`, `MON` = 3-letter uppercase month. |
| `name` | `GOLD` (quoted) | **The underlying/grouping key.** Constant across all monthly contracts of a series. |
| `expiry` | `2024-08-05` | ISO `YYYY-MM-DD`. **Present and reliable** — this is the sort key for near/next/prev. |
| `strike` | `0` | Zero for futures (non-zero only for options). |
| `lot_size` | `1` in this dump | See §5 caveat — do not trust for real lot size. |
| `instrument_type` | `FUT` | Discriminates futures from options (`CE`/`PE`). |
| `segment` | `MCX-FUT` | Clean filter for "commodity futures only". |
| `exchange` | `MCX` | Top-level exchange filter. |

### 1.3 Distinct MCX-FUT underlyings in this snapshot (24 series, 117 contracts)

`ALUMINI, ALUMINIUM, COPPER, COTTONCNDY, CRUDEOIL, CRUDEOILM, GOLD, GOLDGUINEA, GOLDM, GOLDPETAL, KAPAS, LEAD, LEADMINI, MCXBULLDEX, MCXMETLDEX, MENTHAOIL, NATGASMINI, NATURALGAS, NICKEL, SILVER, SILVERM, SILVERMIC, STEELREBAR, ZINC, ZINCMINI`

Each series carries ~3–6 live monthly contracts. **Important:** the underlying name is a prefix family — `GOLD`, `GOLDM`, `GOLDGUINEA`, `GOLDPETAL`, `GOLDMINI`-style variants are *distinct* underlyings. Matching on `name == "GOLD"` (exact) is correct; a substring/`contains` match on "GOLD" would wrongly sweep in `GOLDM`, `GOLDPETAL`, etc. This is a concrete trap for the selection code.

### 1.4 MCX segment/type distribution (this snapshot)

```
segment:  MCX-FUT 117 | MCX-OPT 6250 | INDICES 10
type:     FUT 117 | CE 3125 | PE 3125 | EQ 10
exchange row totals: MCX 6377
```

So futures are a small, cleanly-segmented slice (`MCX-FUT`) of the MCX rows.

### 1.5 Forward-compat: equity/index F&O look identical structurally

NFO futures use the same schema (`segment == NFO-FUT`):

```
8961794,35007,NIFTY24JULFUT,"NIFTY",0,2024-07-25,0,0.05,25,FUT,NFO-FUT,NFO
9002242,35165,BANKNIFTY24JULFUT,"BANKNIFTY",0,2024-07-31,0,0.05,15,FUT,NFO-FUT,NFO
```

The same `name`-group + `expiry`-sort selection logic would generalize to NFO-FUT later. This is a note only — NFO is out of scope for the first pass.

---

## 2. What `instrument_manager.py` does today and what must change

### 2.1 Today's resolution paths

- `get_instrument_token(symbol, is_stock=True, exchange=None)` (`instrument_manager.py:313`):
  - **Stock path** (`is_stock=True`): exact match on `Name` (== `tradingsymbol`, upper-cased) then `_select_preferred_equity_match` picks NSE>BSE (`instrument_manager.py:241`).
  - **Commodity path** (`is_stock=False`): `_normalize_commodity_symbol` (`instrument_manager.py:233`) splits on whitespace and rebuilds `"<first> <last>"` (e.g. `"GOLD PETAL"`), then exact-matches `Name`. This is a *legacy spot-name* scheme and does **not** understand `GOLD24AUGFUT`-style futures tradingsymbols or expiry.
- `search_symbol` (`instrument_manager.py:343`): substring `contains` on `Name`, optional `exchange` filter, exact-match-first ordering.
- `_resolve_ticker_token` in the fetcher (`data_fetcher.py:235`) calls `get_instrument_token(..., is_stock=True)`, then falls back to `is_stock=False`. Neither branch can express "the near-month GOLD future."

**Conclusion:** none of the current entry points can select a contract by expiry. A new resolution capability is required; it is additive, not a rewrite.

### 2.2 What must change conceptually

- **(a) Filter by exchange/segment:** the loaded DataFrame already has `exchange`/`segment` in the default path (§2.3). New code filters `segment == "MCX-FUT"` (or `exchange == "MCX"` + `instrument_type == "FUT"`).
- **(b) Group by underlying:** group rows by `name` (exact), after upper-casing the caller's requested underlying (e.g. `"GOLD"`). Beware prefix-family collisions (§1.3) — use equality, not `contains`.
- **(c) Sort by expiry to find near/next/prev:** parse `expiry` (ISO date) to a date, sort ascending, drop already-expired rows (`expiry >= today`), then index: near = first future expiry, near+1 = second, near-1 = last *expired* contract (or the previously-active one). "Latest-1 = previous month" needs a definition decision (see Open Questions).
- **(d) Select a specific month:** either parse the caller's `("GOLD","DEC",2024)` into a target `expiry` month, or match the `tradingsymbol` pattern `GOLD24DECFUT`. Matching on parsed `expiry` year+month is more robust than string-building the tradingsymbol (avoids weekly/variant naming surprises).

These are all pandas filter/sort operations over the already-loaded frame — no new heavy dependency needed.

### 2.3 Critical constraint: current loader drops the columns selection needs

`_load_instrument_data` (`instrument_manager.py:141`) behaves differently by path:

- **Default/bundled/cached path** (`instrument_manager.py:164`): calls `load_instrument_data()` which does a plain `pd.read_csv` (all 12 columns). It then renames only 4 (`instrument_token→Instrument_Token`, `tradingsymbol→Name`, `name→FullName`, `exchange→Exchange`; `instrument_manager.py:191`). **`expiry`, `strike`, `instrument_type`, `segment`, `lot_size` survive under their original lowercase names.** So they *are* available here.
- **Custom-path branch** (`instrument_manager.py:155`): uses `usecols=["instrument_token","tradingsymbol","name","exchange"]` — **`expiry`/`segment`/`instrument_type` are dropped entirely.** Any user supplying a custom `instrument_id_path` would break commodity selection.

**Implication for the plan:** the custom-path `usecols` list must be widened (or made conditional) so `expiry`, `segment`, `instrument_type` are loaded; and the rename map / downstream code must settle a consistent naming convention for these new columns. This is the single most important internal change and it touches the data-loading seam, not the fetch path.

Also note `name == "GOLD"` maps to the **`FullName`** column after rename, while `tradingsymbol` maps to `Name`. The grouping key for underlyings is therefore the renamed `FullName` column (or the raw `name` if the rename map is left untouched for new columns). The plan must pin down this mapping to avoid confusion.

---

## 3. Feasibility of the fetch path — is it already token-based? YES

The historical fetch is **purely instrument-token driven** and format-agnostic to asset class:

- URL template (`config.py:65`):
  `https://kite.zerodha.com/oms/instruments/historical/{token}/{timeframe}?user_id={userid}&oi=1&from={current_date}&to={next_date}`
  The only instrument-specific field is `{token}`.
- `_fetch_data_chunk` (`data_fetcher.py:279`) formats that URL with `token=` and parses `data.candles`. It already requests `oi=1` and even reads a 7th `OI` column (`data_fetcher.py:347-351`) which it currently drops — OI is meaningful for futures, so this is a "free" future enhancement.
- `fetch_historical_data` (`data_fetcher.py:449`) resolves the token once via `_resolve_ticker_token`, then chunks by date and fans out. Nothing in the chunking, auth, or parsing is equity-specific.

**Verdict on point 3:** once the correct MCX futures instrument token is resolved, the existing fetch path works **unchanged**. If a caller already knows the integer token of `GOLD24DECFUT`, `fetch_historical_data(<token>, ...)` works *today* (subject to `_validate_ticker_token` passing and the account having MCX historical data permission — see §7). The feature is therefore **fundamentally a resolution/selection problem, not a fetch-path problem.**

One caveat: `_validate_ticker_token` (`data_fetcher.py:179`) probes a 28-day `minute` window ending today. For an **expired** contract (near-1, or an old specific month), there may be no candles in the last 28 days, but the probe treats an empty/valid 200 response as success (only `invalid token`/`TokenException` fail it), so it should still pass. This needs live confirmation (§7).

---

## 4. Rate-limit / parallelism implications of multi-contract resolution

- Resolution itself (near, near-1, near+1, specific) is **pure in-memory pandas** over the cached DataFrame — no API calls, so resolving several contracts concurrently costs nothing against the rate limit. The "each on its own thread" requirement is cheap for the *selection* step.
- The real API cost is the subsequent **historical fetch per contract**. Each contract fans out into date chunks (`DEFAULT_CHUNK_DAYS = 30`, `config.py:29`) across `MAX_WORKERS = 10` (`config.py:30`).
- The rate limiter (`rate_limiter.py`) is **per-`RateLimitedThreadPoolExecutor` instance**, not global. Today each `fetch_historical_data` call creates its own executor (`data_fetcher.py:520`). If the new feature fetches N contracts by spinning up N executors concurrently, the effective request rate becomes **N × requests_per_second** — the pacing guarantee is violated. `requests_per_second` is clamped 1–10 (`config.py:20-22`).
- **Design consideration for the planner:** either (a) share one rate limiter / one executor across all contracts in a multi-contract request, or (b) divide the budget across contracts, or (c) fetch contracts sequentially and only parallelize the date chunks. This is a genuine architectural decision, not a detail. Zerodha's documented Kite Connect historical limit is ~3 req/s; the web/`oms` endpoint used here is undocumented, so headroom is unknown (§7).
- `_validate_ticker_token` adds **one extra API call per resolved token** before its fetch. Resolving near/near-1/near+1 = 3 validation calls up front.

---

## 5. Expiry / rollover mechanics for MCX commodities

From the data plus general knowledge (flag live-verify items):

- **Monthly expiry cadence.** Each MCX commodity series has one contract per (most) calendar months. `expiry` in the CSV is a concrete date, e.g. GOLD: `2024-08-05, 2024-10-04, 2024-12-05, 2025-02-05, 2025-04-04, 2025-06-05` — note GOLD skips some months (no Sep/Nov/Jan/Mar), i.e. **not every commodity trades every month.** CRUDEOIL, by contrast, is monthly and consecutive (`Jul, Aug, Sep, Oct, Nov, Dec`). So "previous/next month" must mean **previous/next available contract by expiry order, not calendar arithmetic.** Building `GOLD25JANFUT` by month math would miss — that contract may not exist.
- **Expiry day varies by commodity** (metals ~5th, energy ~19th in this data) and is set by MCX circulars; do not assume a fixed day. Use the `expiry` field verbatim.
- **MCX vs NSE F&O differ.** NSE equity/index F&O expire on the last Thursday/monthly Thursday cadence; MCX commodity expiries follow MCX's own calendar (mid-month for energy, early-month for bullion). This reinforces: rely on the `expiry` column, never hard-code conventions.
- **Rollover point:** "near month" should roll to the next contract at/after the current contract's expiry. Whether to roll on expiry day, or a few days before (when liquidity migrates), is a policy choice for the planner (see Open Questions).
- **Snapshot staleness matters here.** In this bundled CSV the MCX-FUT expiries span only `2024-07-19 … 2025-06-05`, while the repo's "today" context is 2026-09. So the **bundled** file cannot answer "near month" for the current date — near-month resolution *depends on a freshly downloaded/cached instruments file* (see §6). The bundled CSV is only a last-resort fallback (`data_loader.py:169`).

---

## 6. Existing-codebase constraints

- **Python floor: `>=3.8`** (`pyproject.toml`). No `match` statements, no `zoneinfo`-only assumptions, careful with newer typing.
- **Dependencies are intentionally light:** `requests>=2.25`, `pandas>=1.3`, `python-dateutil>=2.8`, `platformdirs>=3.0`. Expiry parsing/sorting can use `pandas.to_datetime` or `dateutil` (both already present) — **no new dependency needed** for selection logic. Adding one would break the "light deps" posture.
- **Mocked-test discipline:** all instrument tests monkeypatch `zerodha_data_fetcher.core.instrument_manager.load_instrument_data` with an in-memory DataFrame (`tests/test_instrument_manager.py:7+`). The shared fixture `sample_instrument_df` (`tests/conftest.py:16`) has only the **4 renamed columns** (`Instrument_Token, Name, FullName, Exchange`) and one MCX row (`GOLD PETAL`). To test rollover, the fixture (or a new one) must add `expiry`, `segment`, `instrument_type` columns and multiple monthly rows per underlying. No live network in tests — the plan must keep that discipline.
- **CSV size & TTL caching:** the bundled CSV is ~6.7 MB / 86k rows. `load_instrument_data` (`data_loader.py:110`) prefers a `platformdirs` cache, re-downloads when older than TTL (`DEFAULT_TTL_MINUTES = 1440` = 24 h, overridable via `ZERODHA_INSTRUMENT_CACHE_TTL`), and falls back to bundled. Reading extra columns adds negligible memory. **The 24 h TTL is coarse for near-month rollover on/around expiry day** — on an expiry day the cache could be up to 24 h stale, momentarily resolving the just-expired contract as "near." Consider a shorter TTL for derivatives use or a targeted refresh (`refresh_instruments`, `instrument_manager.py:215`, already exists and force-downloads).
- **Additive/back-compat expectation:** the codebase keeps deprecated legacy shims (`fetchDataZerodha`, `fetchZerodhaID`). New API surface should be additive (new methods/params), preserving existing `get_instrument_token`/`fetch_historical_data` signatures.

---

## 7. Risks / unknowns / needs live verification

1. **MCX historical permission on the account.** The `oms/.../historical` web endpoint may require the account to be enabled for the commodity segment. Whether it returns candles for MCX tokens for a given user is **unverified** — needs a live call with a real enctoken. *(High priority to confirm before building.)*
2. **Undocumented endpoint rate limits.** The `oms` web endpoint is not the documented Kite Connect API; its true rate ceiling is unknown. Multi-contract concurrency (§4) could trip throttling/bans. Needs live probing.
3. **Expired-contract historical availability.** Can the endpoint return candles for an *already-expired* contract token (needed for near-1 and historical specific months)? Kite Connect generally serves expired-contract history for a limited retention window; the web endpoint's behavior and retention depth are **unverified**.
4. **`_validate_ticker_token` on expired/thin contracts** (`data_fetcher.py:179`): probes the last 28 days at `minute` resolution. For an expired near-1 contract this window has no data; confirm the endpoint returns an empty-but-valid 200 (treated as pass) rather than an error. Live-verify.
5. **`lot_size` is unreliable in this dump** (shows `1` for GOLD, CRUDEOIL, etc.). Real MCX lot sizes differ (contract-specific). Do **not** surface lot_size as authoritative without cross-checking a fresh live instruments file; possibly a stale/placeholder field in this snapshot.
6. **Underlying prefix collisions** (`GOLD` vs `GOLDM`/`GOLDPETAL`/`GOLDGUINEA`, `SILVER` vs `SILVERM`/`SILVERMIC`, `CRUDEOIL` vs `CRUDEOILM`, `NATURALGAS` vs `NATGASMINI`). Selection must use exact `name` equality and expose the mini/variant series as distinct underlyings.
7. **Non-consecutive expiry months** (GOLD skips months). "Previous/next month" must be defined as previous/next *listed* contract by expiry, not calendar month.
8. **Bundled-CSV staleness for near-month** (§5): behavior must depend on a fresh download; document that offline/bundled-only operation cannot resolve current near-month.
9. **Custom `instrument_id_path` regression** (§2.3): widening `usecols` is mandatory or custom-path users lose commodity support silently.
10. **Continuous / back-adjusted series (the big open question)** — see below.

---

## 8. Freshness / reconciliation strategy for new contracts

**Question raised:** as time moves forward, MCX lists new monthly contracts (e.g. `GOLD25AUGFUT`, then `GOLD25OCTFUT`, …). The bundled CSV is a frozen snapshot and will never contain them. Do we need a reconciliation/fetch step that pulls new instrument scrips from Kite and merges them into the CSV?

**Finding: the reconciliation strategy already exists, and it is whole-file replacement — not row-level merge.**

- `download_instruments` (`data_loader.py:81`) fetches the **entire** instrument master from `https://api.kite.trade/instruments` — Kite's **public, unauthenticated** bulk CSV dump that contains *every* live instrument, including all current MCX-FUT months. There is no separate per-symbol "scrip" API call in the codebase; "fetching the instrument scrip from Kite" **is** this bulk download.
- `load_instrument_data` (`data_loader.py:110`) re-downloads whenever the cached copy is older than `cache_ttl_minutes` (default 1440 = 24 h; overridable via `ZERODHA_INSTRUMENT_CACHE_TTL`), and only falls back to the bundled CSV if the download fails (`data_loader.py:169`).
- `refresh_instruments` (`instrument_manager.py:215`) force-downloads on demand, ignoring TTL.

So newly-listed contracts appear **automatically** the next time the TTL lapses or `refresh_instruments()` is called — the whole cached file is discarded and replaced with Kite's current master. Because the dump is public and free, this costs nothing against the historical-fetch rate budget and needs no credentials.

**Recommendation: do NOT build a per-symbol scrip fetch + diff/append reconciliation layer.** Whole-file replacement is strictly simpler and more correct: it cannot leave stale or duplicate rows, cannot drift out of sync with expiries/lot sizes, and requires no merge logic. A row-level reconciler would be more code, more fragile, and buy nothing here.

### 8.1 The real gap: stale-file detection for forward selectors

Whole-file replacement covers *new contracts*; what it does not do is **tell the caller when the file they are resolving against is too stale to answer a forward-looking query**. Two concrete cases:

1. **Offline / bundled-only:** if the download is blocked and the loader falls back to the bundled CSV (expiries `2024-07-19 … 2025-06-05`, §5), a `near`-month resolution silently returns a long-expired contract with no signal that the answer is worthless.
2. **Expiry-day TTL lag:** with a 24 h TTL, on/around an expiry day the cached file can momentarily lack the just-listed far contract or still present the just-expired one as `near` (§7.8).

**Decidable staleness signal (pure, no network):** for a forward selector (`near`/`near_next`), the file is *stale-for-near-month* when — after filtering to the requested underlying — **no contract has `Expiry >= cutoff`** (`cutoff = as_of + roll_offset_days`). This is the sharp signal: missing *far* months never breaks `near` (near is always the earliest future contract), so staleness for `near` reduces to "is there any future contract at all." Surface the newest available expiry alongside, so warnings/errors are actionable. `near_prev` and `specific` (historical) selectors are **exempt** — they depend on expired-contract retention (§7.3), not on file freshness.

**Policy (single `on_stale` flag, default `"warn"`):** `"ignore"` (silent best-guess = today's behavior), `"warn"` (log + set `stale=True` on the returned contract + return best guess; non-breaking), `"error"` (raise `StaleInstrumentDataError`, forcing a refresh), `"refresh"` (call `refresh_instruments()` once, reload, re-resolve; if still stale, degrade to `warn` — the **only** policy that adds a network call, and it is opt-in). Settable per-call and as a constructor default. The bundled-fallback case is independently suspect but is already caught by the content signal (the bundled file's max expiry is in the past), so no extra `source` plumbing is required for the first pass.

**Implementation home:** Phase 3 (§8 of the plan), since it is forward-selector freshness that pairs with auto-rollover — see the implementation plan for the API surface, error type, and tests.

---

## Feasibility verdict

**Highly feasible, and primarily a resolution/selection problem — not a fetch-path problem.** The historical fetch pipeline (`data_fetcher.py`) is entirely instrument-token-driven via a single templated URL (`config.py:65`), so it already works for any MCX futures token once resolved; the parser even already reads the Open Interest column that futures care about. The bulk of the work is a **new contract-selection layer** in the instrument manager that filters by `segment == MCX-FUT`, groups by the underlying `name`, and sorts by the `expiry` column (all data already in the CSV) to pick near / near-1 / near+1 / a specific month — plus a mandatory fix to widen the loader's column set (the custom-path `usecols` and the rename map currently drop `expiry`/`segment`/`instrument_type`). Main risks are operational rather than architectural: live confirmation of MCX historical permissions and expired-contract retention on the undocumented `oms` endpoint, a shared-rate-limiter decision for multi-contract concurrency, and cache-TTL freshness around expiry days.

## Open questions / needs live verification

- **Continuous / back-adjusted contract stitching (explicitly flagged open):** For long historical series across many expired monthly contracts, do we stitch a continuous series? If so, what roll rule (calendar expiry date vs volume/OI crossover) and what adjustment method (no adjust / ratio / difference back-adjust)? This is non-trivial, changes output semantics, and is deferred as its own design question — the discovery only flags it. Back-adjustment also requires OI/volume data the endpoint may or may not reliably return for expired contracts.
- **Roll timing policy:** roll near-month exactly on expiry date, or N days before (liquidity migration)? Needs a product decision + live liquidity check.
- **near-1 definition:** last-expired contract vs the contract active in the prior calendar month vs prior *listed* expiry. Must be pinned down (non-consecutive months complicate it).
- **Live: MCX historical permission + expired-contract retention depth** on the `oms` endpoint (risks 1, 3).
- **Live: true rate ceiling** of the web `oms` historical endpoint under multi-contract concurrency (risk 2).
- **Live: `_validate_ticker_token` behavior** on expired/thin contracts (risk 4).
- **Live: authoritative `lot_size`** (and tick_size) from a fresh instruments file (risk 5).
- **Naming convention** for the newly-surfaced columns (keep raw `expiry`/`segment`/`instrument_type`, or rename to PascalCase to match `Instrument_Token`/`Name`/`FullName`/`Exchange`) — an internal consistency decision for the plan.

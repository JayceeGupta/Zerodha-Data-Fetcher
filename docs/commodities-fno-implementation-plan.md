# Implementation Plan: MCX Commodity Futures + Auto-Rollover

**Status:** Plan only. No source under `src/` or `tests/` is modified by this document.
**Primary input:** `docs/commodities-fno-discovery.md` (all "discovery §N" references below point at it).
**Target:** a separate future branch (e.g. `feat/mcx-commodity-futures`), executed phase by phase.
**Python floor:** `>=3.8` — no `match`, no PEP-604 `X | Y` in annotations, use `typing.Optional/Union/Literal` (discovery §6).
**Dependency posture:** add nothing new — expiry parsing uses `pandas.to_datetime` / `dateutil`, both already present (discovery §6).

The discovery verdict stands: this is a **resolution/selection problem, not a fetch-path problem**. The historical fetch pipeline (`data_fetcher.py:279` `_fetch_data_chunk`, templated URL at `config.py:65-68`) is purely instrument-token-driven and already works for any MCX futures token once resolved (discovery §3). The work is (a) a mandatory loader-column fix, (b) a new contract-selection layer in `instrument_manager.py`, (c) auto-rollover semantics, (d) a shared-rate-limit design for multi-contract fetches. Continuous/back-adjusted stitching is left as an explicit open decision (§6 below).

---

## 0. Naming convention decision (resolve first — everything depends on it)

Discovery §2.3 flags an internal ambiguity: the default loader renames only 4 columns to PascalCase (`instrument_token→Instrument_Token`, `tradingsymbol→Name`, `name→FullName`, `exchange→Exchange`; `instrument_manager.py:191-196`) while `expiry`/`strike`/`instrument_type`/`segment`/`lot_size` survive under raw lowercase names.

**Decision for this plan:** extend the rename map so the new columns are also PascalCase, keeping the DataFrame internally consistent:

| Raw CSV column | Internal column |
|---|---|
| `instrument_token` | `Instrument_Token` (existing) |
| `tradingsymbol` | `Name` (existing) |
| `name` | `FullName` (existing — this is the **underlying/grouping key**, e.g. `GOLD`) |
| `exchange` | `Exchange` (existing) |
| `expiry` | `Expiry` (new) |
| `segment` | `Segment` (new) |
| `instrument_type` | `InstrumentType` (new) |

`strike` and `lot_size` are **not** surfaced (discovery §5: `lot_size` is unreliable/placeholder `1` in the dump — do not expose as authoritative). All new selection code references `FullName` for the underlying, `Segment`/`InstrumentType`/`Exchange` for filtering, and `Expiry` for sorting. This keeps `Name` meaning "tradingsymbol" as it does today, so no existing code path changes meaning.

**Trap to encode as a comment/constant:** the underlying-grouping key is `FullName` (raw `name`), NOT `Name` (raw `tradingsymbol`). Getting these two backwards is the most likely bug in the new layer.

---

## 1. Proposed public API

Backward compatibility is mandatory (discovery §6 — the repo already keeps `fetchDataZerodha`/`fetchZerodhaID` shims). Every existing signature is preserved; all additions are new methods and new keyword-only params.

### 1.1 New value object: `ContractSelection` (dataclass, in a new module `core/contract_selector.py`)

```python
from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass(frozen=True)
class ResolvedContract:
    underlying: str          # FullName, e.g. "GOLD"
    tradingsymbol: str       # Name, e.g. "GOLD24DECFUT"
    instrument_token: int
    expiry: date
    segment: str             # "MCX-FUT"
    exchange: str            # "MCX"
    selector: str            # "near" | "near_prev" | "near_next" | "specific"
    stale: bool = False      # True if resolved from a stale-for-near-month file (§4.4)
    newest_available_expiry: Optional[date] = None  # newest FUT expiry seen for this underlying
```

`@dataclass(frozen=True)` is 3.8-safe. `ResolvedContract` is what all selection methods return, so callers get the token *and* the audit trail (which contract, which expiry, which selector rule fired). `stale`/`newest_available_expiry` let a caller using `on_stale="warn"` (§4.4) inspect freshness programmatically without parsing log output.

### 1.2 New methods on `ZerodhaInstrumentManager`

Added alongside the existing `get_instrument_token` (`instrument_manager.py:313`) — not replacing it.

```python
def get_futures_contracts(
    self,
    underlying: str,
    *,
    exchange: str = "MCX",
    segment: str = "MCX-FUT",
    include_expired: bool = False,
    as_of: Optional[date] = None,      # defaults to date.today()
) -> "pd.DataFrame":
    """All futures rows for one underlying, sorted ascending by Expiry.

    Exact-equality match on FullName (never substring — GOLD vs GOLDM
    collision, discovery §1.3). Columns include Instrument_Token,
    tradingsymbol, Expiry, Segment, Exchange.
    """

def resolve_futures_contract(
    self,
    underlying: str,
    selector: str = "near",            # "near" | "near_prev" | "near_next"
    *,
    exchange: str = "MCX",
    segment: str = "MCX-FUT",
    as_of: Optional[date] = None,
    roll_offset_days: int = 0,         # roll N days before expiry (§4)
    on_stale: Optional[str] = None,    # "ignore"|"warn"|"error"|"refresh"; None → instance default (§4.4)
) -> Optional["ResolvedContract"]:
    """Resolve near / previous-listed / next-listed contract by expiry.

    For forward selectors (near/near_next), applies the freshness policy
    in §4.4 when the loaded file has no contract expiring on/after cutoff.
    """

def resolve_specific_contract(
    self,
    underlying: str,
    year: int,
    month: int,                        # 1..12, matched against Expiry month
    *,
    exchange: str = "MCX",
    segment: str = "MCX-FUT",
) -> Optional["ResolvedContract"]:
    """Resolve a named month/year contract by parsed Expiry (year, month).

    Matches on parsed Expiry year+month, NOT by string-building the
    tradingsymbol (discovery §2.2(d) — avoids weekly/variant surprises).
    """
```

### 1.3 New method on `ZerodhaDataFetcher`

```python
def fetch_futures_historical_data(
    self,
    underlying: str,
    start_date: date,
    end_date: date,
    *,
    selector: str = "near",            # near | near_prev | near_next | specific
    year: Optional[int] = None,        # required when selector == "specific"
    month: Optional[int] = None,       # required when selector == "specific"
    exchange: str = "MCX",
    segment: str = "MCX-FUT",
    timeframe: str = "minute",
    roll_offset_days: int = 0,
    on_stale: Optional[str] = None,    # forwarded to resolution (§4.4)
    chunk_failure_mode: Optional[ChunkFailureMode] = None,
) -> "pd.DataFrame":
    """Resolve one MCX futures contract, then fetch it via the existing
    fetch path. Output schema unchanged: [Date, Time, Open, High, Low,
    Close, Volume]."""

def fetch_futures_bundle(
    self,
    underlying: str,
    start_date: date,
    end_date: date,
    *,
    selectors: "Sequence[str]" = ("near_prev", "near", "near_next"),
    timeframe: str = "minute",
    roll_offset_days: int = 0,
    on_stale: Optional[str] = None,    # forwarded to resolution (§4.4)
    chunk_failure_mode: Optional[ChunkFailureMode] = None,
) -> "Dict[str, pd.DataFrame]":
    """Resolve and fetch several selectors for one underlying concurrently,
    each selector on its own thread (discovery requirement). Returns a dict
    keyed by selector. Uses one shared rate limiter across all contracts
    (§5)."""
```

**Why `fetch_historical_data` stays untouched:** it already accepts an `int` token (discovery §3 — a known GOLD24DECFUT token works *today*). The new methods layer resolution on top; a caller who resolves a contract themselves can still pass `resolved.instrument_token` into the old method.

### 1.4 Example call sites (all four selection modes)

```python
fetcher = ZerodhaDataFetcher(requests_per_second=3)

# 1) near / latest active month
df = fetcher.fetch_futures_historical_data("GOLD", start, end, selector="near")

# 2) latest-1 (previous LISTED contract by expiry, discovery §1.3/§7.7)
df = fetcher.fetch_futures_historical_data("CRUDEOIL", start, end, selector="near_prev")

# 3) latest+1 (next listed contract by expiry)
df = fetcher.fetch_futures_historical_data("SILVER", start, end, selector="near_next")

# 4) specific named month/year
df = fetcher.fetch_futures_historical_data(
    "GOLD", start, end, selector="specific", year=2024, month=12
)

# per-thread resolution of near-1 / near / near+1 together, shared limiter
bundle = fetcher.fetch_futures_bundle("GOLD", start, end,
                                      selectors=("near_prev", "near", "near_next"))
near_df = bundle["near"]

# resolution only (no fetch) — pure in-memory, cheap (discovery §4)
im = ZerodhaInstrumentManager()
contract = im.resolve_futures_contract("GOLD", "near")
print(contract.tradingsymbol, contract.expiry)
```

---

## 2. Contract-resolution layer

New module `src/zerodha_data_fetcher/core/contract_selector.py` holds the pure selection logic so it is unit-testable without any manager/fetcher wiring. `ZerodhaInstrumentManager` methods (§1.2) are thin adapters that load the DataFrame and delegate.

### 2.1 Filtering (discovery §2.2(a), §1.4)

Given the loaded frame with the columns from §0:

1. `Exchange == exchange.upper()` (default `"MCX"`).
2. `Segment == segment.upper()` (default `"MCX-FUT"`) — the clean "futures only" filter (discovery §1.4: `MCX-FUT` = 117 rows, cleanly segmented from `MCX-OPT`).
3. Belt-and-braces: `InstrumentType == "FUT"` (discriminates FUT from CE/PE — discovery §1.2).

### 2.2 Grouping by underlying (discovery §1.3, §7.6 — the collision trap)

- Match on `FullName == underlying.strip().upper()` using **exact equality**.
- **Never** `str.contains` — `contains("GOLD")` wrongly sweeps in `GOLDM`, `GOLDPETAL`, `GOLDGUINEA`; `contains("SILVER")` sweeps `SILVERM`/`SILVERMIC`; `CRUDEOIL`/`CRUDEOILM`; `NATURALGAS`/`NATGASMINI`. Mini/variant series are distinct underlyings and must be requested by their exact name.

### 2.3 Sorting & the near/prev/next/specific selectors (discovery §2.2(c), §5, §7.7)

Parse `Expiry` once via `pd.to_datetime(...).dt.date`, sort ascending. Let `as_of = as_of or date.today()` and `cutoff = as_of + timedelta(days=roll_offset_days)` (roll early — §4).

- **`near`** = first contract with `Expiry >= cutoff` (earliest not-yet-rolled expiry).
- **`near_next`** = the contract immediately after `near` in expiry order (the second `Expiry >= cutoff`). If none, `None`.
- **`near_prev`** = the contract immediately **before** `near` in the full expiry-sorted list — i.e. the **previous listed contract by expiry**, which is the most recently expired one relative to `as_of`. This is the pinned definition (discovery §7.7 / open-question "near-1"): previous *listed* expiry, never calendar-month arithmetic. GOLD skips months (Aug, Oct, Dec, Feb… — discovery §5), so `GOLD25JANFUT` may not exist; stepping by list index is correct, month math is wrong.
- **`specific(year, month)`** = the row whose parsed `Expiry.year == year and Expiry.month == month`. If a series ever lists two contracts expiring in the same month, pick the earliest and log a warning. No dependence on `today`; works for arbitrary historical months subject to CSV retention (§9).

`near_prev` requires expired rows to be present, so `get_futures_contracts(include_expired=True)` must NOT drop `Expiry < as_of`. `near`/`near_next` operate on the future slice. Implement by keeping the full sorted list and computing the split index at `cutoff` rather than pre-filtering.

### 2.4 Edge cases the selector must handle

- Underlying not found / no futures rows → return `None` (mirror `get_instrument_token` returning `None`, `instrument_manager.py:332-334`); do not raise.
- `near_next` past the last listed contract → `None` (caller decides whether that is an error).
- `near_prev` when the earliest listed contract is the near one (no prior expiry) → `None`.
- Unparseable `Expiry` values → drop the row with a debug log rather than crashing the whole selection.

---

## 3. The mandatory loader fix (discovery §2.3, §7.9)

This is the single highest-priority internal change; without it the custom-path and the rename map silently drop the columns selection needs.

### 3.1 Custom-path `usecols` (`instrument_manager.py:155-163`)

Today:
```python
self._instrument_data = pd.read_csv(
    self.instrument_id_path,
    usecols=["instrument_token", "tradingsymbol", "name", "exchange"],
)
```
The `usecols` list drops `expiry`/`segment`/`instrument_type` entirely — any user supplying `instrument_id_path` loses commodity support (discovery §2.3). **Change:** widen to the derivative-aware set, but make it resilient to older/custom CSVs that lack the new columns (do not hard-fail):

- Preferred: read the CSV header first, then pass `usecols` = intersection of the desired set with the columns actually present, OR pass a `usecols=callable` that keeps any of `{instrument_token, tradingsymbol, name, exchange, expiry, segment, instrument_type}`.
- Desired set: `instrument_token, tradingsymbol, name, exchange, expiry, segment, instrument_type`.
- `instrument_token` remains the only strictly-required column (the existing guard at `instrument_manager.py:182-185` already enforces this).

### 3.2 Default-path parity (`instrument_manager.py:164-167` + `data_loader.py:156/163/176`)

The default path calls `load_instrument_data()` which does a plain `pd.read_csv` (all 12 columns) — the new columns already survive here (discovery §2.3). No change to `data_loader.py` is strictly required for *columns*, but see §4/§7 for the TTL knob. Confirm the three `pd.read_csv` call sites in `data_loader.py` (cache `:156`, downloaded `:163`, bundled `:176`) do not pass a restrictive `usecols` — they don't today, so they are fine.

### 3.3 Rename map (`instrument_manager.py:191-204`)

Extend `column_mapping` with the three new entries from §0 (`expiry→Expiry`, `segment→Segment`, `instrument_type→InstrumentType`). The existing `existing_mapping` comprehension (`:197-201`) already filters to columns actually present, so a custom CSV missing these columns just won't get them renamed — no crash. Downstream selection code must therefore tolerate the columns being absent (treat "column missing" as "no futures available for this source").

### 3.4 Backward-compat implications

- **Existing stock path:** unaffected — `Name`/`FullName`/`Exchange`/`Instrument_Token` keep their current meaning; only *additional* columns appear. `get_instrument_token`, `search_symbol`, `fetch_instrument_ids` are untouched.
- **Existing tests:** `tests/test_instrument_manager.py:7-18` monkeypatches `load_instrument_data` to return a frame with **raw lowercase** names and lets `_load_instrument_data` do the rename. Since `existing_mapping` filters to present columns, the old 4-column fixtures still work unchanged. New tests add the extra columns (§7).
- **Memory:** three extra columns over 86k rows is negligible (discovery §6).
- **Custom CSV regression closed:** widening `usecols` is exactly what discovery §7.9 flags as "mandatory or custom-path users lose commodity support silently."

---

## 4. Auto-rollover semantics (discovery §5, §6)

"Auto-rollover" here means: **the `near` selector re-resolves to a fresh contract as time passes**, because it is computed from `as_of`/`today` against the `Expiry` column on each call. There is no persistent rollover state; correctness depends on (a) the resolution rule and (b) instrument-file freshness.

### 4.1 Roll timing (`roll_offset_days`)

- Default `roll_offset_days=0` → `near` rolls **on** the contract's expiry date: once `today > expiry`, that contract drops out of the `Expiry >= cutoff` slice and the next listed contract becomes `near`.
- `roll_offset_days=N` → roll `N` days **before** expiry (liquidity migrates ahead of expiry — discovery §5 open question "roll timing"). Implemented purely as `cutoff = today + timedelta(days=N)` in §2.3. This is a knob, not a hard-coded policy; the discovery deliberately leaves the "right" N as a product decision pending a live liquidity check.
- Expiry day itself varies by commodity (metals ~5th, energy ~19th — discovery §5); the rule never hard-codes a day, it always reads the `Expiry` column verbatim.

### 4.2 Cache-TTL staleness around expiry (discovery §6, §7.8)

The instrument cache TTL is 24 h (`_DEFAULT_TTL_MINUTES = 1440`, `data_loader.py:21`; `Config.DEFAULT_INSTRUMENT_CACHE_TTL_MINUTES`, `config.py:34`). On/near an expiry day a 24 h-stale file can momentarily resolve the just-expired contract as `near`, or lack a newly-listed far contract (discovery §7.8). Also, the bundled CSV spans only `2024-07-19 … 2025-06-05` while "today" is 2026-09 — **bundled-only/offline operation cannot resolve current near-month** (discovery §5); document this loudly and treat bundled as last-resort only.

Mitigations (in preference order, all already have hooks):
1. **Recommended default:** when `fetch_futures_*`/`resolve_futures_contract` is used with a `near`/`near_next` selector, allow a lower effective TTL for derivatives. Add an optional `ZERODHA_INSTRUMENT_CACHE_TTL` override guidance in docs, and/or pass a smaller `cache_ttl_minutes` to `ZerodhaInstrumentManager` when constructing it for commodity use.
2. **Targeted refresh:** `refresh_instruments()` already exists and force-downloads ignoring TTL (`instrument_manager.py:215-231`, package-level wrapper `__init__.py:90-101`). Document "call `refresh_instruments()` on expiry day before resolving near-month."
3. Do **not** silently auto-refresh inside resolution (would add an unpredictable network call to a "pure in-memory" step — discovery §4). Keep refresh explicit.

### 4.3 How per-thread near/prev/next composes

All three selectors read the **same in-memory DataFrame** and differ only by list index (§2.3). Resolution is pure pandas with no API calls (discovery §4), so resolving near/prev/next concurrently is cheap and race-free (read-only access to a shared frame). `fetch_futures_bundle` resolves all requested selectors up front (cheap), de-duplicates identical tokens (e.g. if `near_next` doesn't exist it's dropped), then fans the *fetches* out under one shared limiter (§5). Each selector's fetch runs on its own thread as required, but they share the pacing budget.

### 4.4 Freshness / reconciliation policy for forward selectors (discovery §8)

**Reconciliation strategy = whole-file replacement, already implemented (discovery §8).** New contracts arrive via `download_instruments` (`data_loader.py:81`, the public `https://api.kite.trade/instruments` bulk dump) on TTL lapse or `refresh_instruments()` — there is **no** per-symbol scrip fetch and **no** row-level merge, and we deliberately do not build one. This subsection only adds *detection* of a file too stale to answer a forward-looking query, plus a configurable response.

**Staleness signal (pure, no network).** In `contract_selector.py`, compute for the requested underlying: `future = [c for c in contracts if c.expiry >= cutoff]` (`cutoff` from §2.3/§4.1). The file is **stale-for-near-month** when `future` is empty (no contract expiring on/after cutoff). Only `near`/`near_next` consult this; `near_prev` and `specific` are exempt (they rely on expired-contract retention, §9, not freshness). Also compute `newest_available_expiry = max(expiry for all contracts of the underlying)` for actionable messaging.

**`on_stale` policy** (per-call param on `resolve_futures_contract`/`fetch_futures_*`, plus an instance default set in `ZerodhaInstrumentManager.__init__` / `ZerodhaDataFetcher.__init__`; per-call `None` → instance default; instance default `"warn"`):

| Value | Behavior when stale-for-near-month |
|---|---|
| `"ignore"` | Return best available (or `None`) with no signal — today's behavior. |
| `"warn"` (default) | `logger.warning(...)` naming `newest_available_expiry` vs `as_of`; return the best-guess contract with `stale=True`. **Non-breaking.** |
| `"error"` | Raise `StaleInstrumentDataError` (new, in `core/contract_selector.py` or the manager's errors module). Message includes underlying, `newest_available_expiry`, `as_of`, and "call `refresh_instruments()`". |
| `"refresh"` | Call `self.refresh_instruments()` **once** (force-download, `instrument_manager.py:215`), reload the frame, re-resolve. If still stale, **degrade to `warn`** (do not loop, do not raise). The **only** policy that performs a network call — opt-in. |

**Placement & layering.** The pure staleness computation lives in `contract_selector.py` (unit-testable with injected `as_of`, no I/O). The `"refresh"` action requires the manager (it owns `refresh_instruments()` and the loaded frame), so the manager method interprets the policy: selector returns `(contract, is_stale, newest_expiry)`; the manager decides warn/error/refresh. This keeps the selector network-free (preserves the discovery §4 "resolution is pure in-memory" property) while the manager owns the one optional refresh. Validate `on_stale` against the allowed set and raise `ValueError` on an unknown value.

**Bundled-fallback corroboration.** When the loader used the bundled CSV (max expiry 2025-06-05, discovery §5), the content signal already fires for any current `as_of`, so no separate `source` flag is threaded through in this pass — noted as a possible later refinement if we want to warn even when a bundled file happens to still contain a future contract.

---

## 5. Concurrency / rate-limit design (discovery §4, §7.2 — resolves a real risk)

**The risk (discovery §4):** the limiter lives inside each `RateLimitedThreadPoolExecutor` instance (`rate_limiter.py:87` creates one `RequestRateLimiter` per executor), and `fetch_historical_data` creates a fresh executor per call (`data_fetcher.py:520-523`). Fetching N contracts by calling `fetch_historical_data` N times concurrently spins up N executors → **N × requests_per_second** actual rate, violating the pacing guarantee. `requests_per_second` is clamped 1–10 (`config.py:20-22`); the `oms` endpoint's true ceiling is undocumented (discovery §7.2).

**Options considered:**

| Option | Mechanism | Pro | Con |
|---|---|---|---|
| A. Shared limiter | One `RequestRateLimiter` shared by all contracts' fetches (either one executor for all date-chunks across all contracts, or many executors constructed with a shared limiter object) | Honors the global rate exactly; max throughput within budget | Requires threading a limiter through the executor / small refactor of `RateLimitedThreadPoolExecutor` to accept an injected limiter |
| B. Budget split | Give each of N contracts `requests_per_second / N` (min 1) | Simple; no shared-state refactor | Wastes budget when contracts finish at different times; rounding to min 1 can still exceed budget for large N |
| C. Sequential contracts | Fetch contracts one at a time; only parallelize date chunks (today's behavior per call) | Zero refactor; provably within budget | Defeats the "each contract on its own thread" requirement; slowest |

**Recommendation: Option A (shared limiter), implemented as the least-invasive variant.** Add an optional `rate_limiter` parameter to `RateLimitedThreadPoolExecutor.__init__` (`rate_limiter.py:68`): if a `RequestRateLimiter` is passed, use it instead of constructing a new one; otherwise behave exactly as today (full backward compatibility — existing single-call path is unchanged). Then `fetch_futures_bundle` constructs **one** `RequestRateLimiter(self.requests_per_second)` and either:
- submits every contract's date-chunks into a **single** shared executor (simplest, one pool), or
- passes the shared limiter into one executor per contract.

Prefer the single shared executor: build the full list of `(contract, date_chunk)` param tuples across all contracts, submit them all to one `RateLimitedThreadPoolExecutor(max_workers=Config.MAX_WORKERS, requests_per_second=self.requests_per_second)`, and demultiplex results back per contract using the token embedded in each param tuple. This gives exactly one limiter, one pool, honors `MAX_WORKERS` and the rate, and still runs contracts concurrently.

**Extra cost to budget for:** `_validate_ticker_token` (`data_fetcher.py:179`) adds one API call per resolved token before its fetch (discovery §4). near/prev/next = 3 validation calls up front. These must also pass through the shared limiter (or be counted against the budget). Consider making validation optional/skippable for the bundle path once §9 live checks confirm expired-contract probes behave (discovery §3 caveat, §7.4).

---

## 6. Continuous / back-adjusted contract stitching — OPEN DESIGN DECISION

Discovery §7.10 and the "Open questions" section explicitly flag this as non-trivial and deferred; this plan surfaces the options and a recommendation but does **not** silently pick a default.

**The question:** for a long historical series spanning many expired monthly contracts, do we stitch them into one continuous series, and if so how do we handle the price gap at each roll?

| Option | What it does | Backtesting impact | Trade-offs |
|---|---|---|---|
| **6a. No stitching (per-contract)** | Return each contract separately (what `fetch_futures_bundle` already does — a dict keyed by selector/contract). No continuous series. | Honest raw prices; user stitches if they want. No fabricated data. | Not directly backtestable as one instrument; user must handle rolls. **Lowest risk, no hidden semantics.** |
| **6b. Ratio (proportional) back-adjust** | At each roll, multiply all older data by (new_price / old_price) at the roll boundary so the series is continuous multiplicatively. | Good for %-return / log-return strategies; ratios preserved; no negative prices. | Absolute historical price levels are distorted; re-adjusts whenever the anchor (latest contract) changes, so the whole history shifts over time — non-reproducible unless you pin an as-of date. |
| **6c. Difference (additive) back-adjust** | At each roll, add a constant offset so the series is continuous additively. | Common in futures backtesting (e.g. Panama canal method); preserves absolute point moves. | Can produce negative historical prices for deep contango/backwardation; also re-anchors over time. |

**Roll rule for stitching (orthogonal sub-decision):** calendar expiry date (from the `Expiry` column, already available) vs volume/OI crossover. Volume/OI crossover needs reliable volume/OI on expired contracts, which the `oms` endpoint may not return dependably (discovery §7.10) — and the fetch path currently *drops* the OI column (`data_fetcher.py:349-351`), though it's a "free" enhancement to keep it (discovery §3). Calendar-expiry roll is implementable today with zero new data.

**Recommendation:** ship **6a (no stitching)** in the initial feature and expose clean per-contract data plus the `ResolvedContract` metadata (expiry, tradingsymbol) needed for a downstream stitcher. Defer 6b/6c to a **separate follow-up** ("Phase 5", §8) gated on the live verification of expired-contract retention and OI/volume reliability (§9). Rationale: 6a introduces no fabricated data and no time-varying re-anchoring semantics, keeps the output schema stable, and unblocks the core feature; stitching is a genuine product decision that should not be made implicitly. If/when stitching lands, make the adjustment method an explicit parameter (`adjust="none"|"ratio"|"diff"`) with `"none"` the default and a pinned `as_of` anchor for reproducibility.

---

## 7. Testing strategy (keep the fully-mocked discipline — discovery §6)

All instrument tests monkeypatch `zerodha_data_fetcher.core.instrument_manager.load_instrument_data` with an in-memory DataFrame (`tests/test_instrument_manager.py:7-18`); fetcher tests use `FakeExecutor`/`FakeFuture`/`fake_as_completed` and a `FakeAuthManager` (`tests/conftest.py:105-181`). No live network anywhere. New tests follow the same pattern.

### 7.1 New fixtures (in `tests/conftest.py`)

- `sample_mcx_futures_df`: a frame with the **raw lowercase** columns (so `_load_instrument_data`'s rename is exercised, matching the existing test convention at `test_instrument_manager.py:9-18`): `instrument_token, tradingsymbol, name, exchange, expiry, segment, instrument_type`. Include:
  - GOLD with **non-consecutive** expiries (e.g. 2024-08-05, 2024-10-04, 2024-12-05, 2025-02-05 — mirrors discovery §5, no Sep/Nov/Jan) so `near_prev`/`near_next` cannot be faked by month math.
  - CRUDEOIL with **consecutive** monthly expiries (Jul, Aug, Sep 2024).
  - Collision rows: `GOLDM`, `GOLDPETAL`, `GOLDGUINEA`, `SILVER` + `SILVERM` — same tradingsymbol family, distinct `name` (discovery §1.3/§7.6).
  - A couple of MCX-OPT rows (`segment=MCX-OPT`, `instrument_type=CE/PE`, non-zero strike) that must be filtered out.
  - Existing equity rows (INFY/RELIANCE) to prove the stock path is unaffected.
- Use a **fixed `as_of` date** injected into the selector (never `date.today()` directly in the tested function) so expiry-relative tests are deterministic.

### 7.2 Selection unit tests (against `contract_selector.py`, pure — no manager)

1. `near` returns the earliest contract with `Expiry >= as_of`.
2. `near_next` returns the second future contract; returns `None` past the last listed.
3. `near_prev` returns the previous **listed** contract by expiry (most recently expired), **not** the prior calendar month — assert specifically against the GOLD non-consecutive series (skipped-month proof).
4. `specific(2024, 12)` returns GOLD24DECFUT by parsed expiry; `specific(2024, 11)` (a skipped month) returns `None`.
5. **Collision test:** `resolve_futures_contract("GOLD", ...)` never returns a `GOLDM`/`GOLDPETAL`/`GOLDGUINEA` row; `"SILVER"` never returns `SILVERM`.
6. Segment filter: MCX-OPT / CE / PE rows are excluded even when `name` matches.
7. `roll_offset_days=N`: with `as_of` set just before an expiry, offset flips `near` to the next contract (roll-early behavior).
8. Underlying-not-found and empty-futures-frame → `None` (no exception).
9. Unparseable `expiry` row is dropped, not fatal.

### 7.3 Loader tests

10. Custom-path (`instrument_id_path`) CSV **with** the new columns → `Expiry`/`Segment`/`InstrumentType` present after load (regression guard for discovery §7.9). Write a tiny temp CSV in the test.
11. Custom-path CSV **without** the new columns (old 4-column file) → still loads, stock path still works, futures resolution returns `None` gracefully.
12. Rename map: raw lowercase → PascalCase for all 7 columns; extra raw columns (strike/lot_size) are ignored without error.
13. Existing 4-column fixtures (`sample_instrument_df`) still pass unchanged (back-compat).

### 7.4 Fetcher integration tests (mocked executor)

14. `fetch_futures_historical_data("GOLD", selector="near")` resolves to the near token and passes it into the existing chunking path; assert the token in the submitted param tuples (via `FakeExecutor.submitted_params`).
15. `selector="specific"` without `year`/`month` → clear `ValueError`.
16. `fetch_futures_bundle` with `("near_prev","near","near_next")` returns a dict with the right keys and each maps to the expected token.
17. **Shared-limiter test:** assert `fetch_futures_bundle` constructs exactly one limiter / one executor for all contracts (assert on a spy count), proving the discovery §4 N× bug is closed.
18. `RateLimitedThreadPoolExecutor` with an injected `rate_limiter` uses it; without one, constructs its own (back-compat).
19. Output schema of the futures fetch is exactly `[Date, Time, Open, High, Low, Close, Volume]` (unchanged; reuse `dummy_chunk_df`).

### 7.5 Freshness-policy tests (discovery §8, plan §4.4)

Use `sample_mcx_futures_df` with a **fixed `as_of` set AFTER every expiry in the fixture** (so the file is stale-for-near-month), plus a fresh-file case (`as_of` before the latest expiry).

20. **`warn` (default):** stale file + `near` → returns the best-guess contract with `stale=True` and `newest_available_expiry` set; a warning is logged (assert via `caplog`). No exception.
21. **`error`:** stale file + `near`/`on_stale="error"` → raises `StaleInstrumentDataError`; message contains the underlying and `newest_available_expiry`.
22. **`refresh`:** stale file + `on_stale="refresh"` → `refresh_instruments` is called exactly once (spy/monkeypatch); after a monkeypatched refresh swaps in a fresh frame, resolution returns a non-stale contract. If the refresh still yields a stale frame, it degrades to `warn` (no raise, no second refresh — assert call count == 1).
23. **`ignore`:** stale file + `on_stale="ignore"` → no warning logged, `stale` left `False`, best-guess (or `None`) returned.
24. **Fresh file:** `as_of` before latest expiry → `stale=False`, no warning, regardless of `on_stale`.
25. **Exempt selectors:** `near_prev` and `specific(year, month)` never trigger the stale policy even on a stale-for-near file (assert no warning / no raise).
26. **Unknown policy value** → `ValueError`.
27. **Instance default vs per-call:** manager constructed with `on_stale="error"` raises on stale `near`; a per-call `on_stale="warn"` overrides it to warn (per-call `None` uses the instance default).

---

## 8. Phased rollout (ordered, independently shippable)

**Phase 1 — Loader fix + segment-aware data (foundation).**
Scope: §0 naming decision, §3 loader changes (widen custom-path `usecols`, extend rename map), new `get_futures_contracts` returning a filtered/sorted frame.
Acceptance: tests 10–13, and `get_futures_contracts("GOLD")` returns only MCX-FUT GOLD rows sorted by expiry; all existing tests still green. Shippable on its own (adds a read-only query method).

**Phase 2 — Selection modes.**
Scope: §2 `contract_selector.py` + `resolve_futures_contract` (near/prev/next) + `resolve_specific_contract`, `ResolvedContract` dataclass.
Acceptance: tests 1–9. Selectors correct against non-consecutive expiries and collision families. No fetch/network involved. Shippable (pure resolution API).

**Phase 3 — Auto-rollover + freshness policy + single-contract fetch.**
Scope: §4 roll timing (`roll_offset_days`, cutoff logic), §4.4 `on_stale` freshness policy (`StaleInstrumentDataError`, `ResolvedContract.stale`/`newest_available_expiry`, instance-default + per-call flag, opt-in `"refresh"`), TTL/refresh guidance, `fetch_futures_historical_data` wiring resolution into the existing single-executor fetch path.
Acceptance: tests 14, 15, 19, 20–27; documented expiry-day refresh workflow; near-month re-resolves as `as_of` advances (deterministic test with injected dates). Shippable (single-contract commodity fetch end to end).

**Phase 4 — Concurrency hardening + bundle fetch.**
Scope: §5 injectable shared limiter on `RateLimitedThreadPoolExecutor`, `fetch_futures_bundle` with one shared limiter/executor across contracts, per-thread selector resolution.
Acceptance: tests 16, 17, 18; measured request rate stays within `requests_per_second` for multi-contract fetches (unit-level spy on limiter calls). Shippable (multi-contract concurrent fetch, rate-safe).

**Phase 5 (deferred, gated) — Continuous/back-adjusted stitching.**
Scope: §6 decision, only after §9 live checks confirm expired-contract retention + OI/volume reliability. Add `adjust="none"|"ratio"|"diff"` with pinned as-of anchor; optionally stop dropping the OI column (`data_fetcher.py:349-351`).
Acceptance: reproducible stitched series for a fixed as-of; explicit product sign-off on default. Not part of the initial feature.

Each phase leaves `main`-mergeable state: existing signatures preserved, new surface additive, tests green.

---

## 9. Risks & live-verification checklist (pre-implementation gates)

Carried forward from discovery §7. These are **operational unknowns about the undocumented `oms` endpoint** and must be verified with a real enctoken **before** or during Phase 3 (they gate the fetch, not the resolution logic, so Phases 1–2 can proceed in parallel).

1. **MCX historical permission on the account** (discovery §7.1, high priority). Confirm the `oms/.../historical` endpoint returns candles for an MCX-FUT token for the target user. If the segment isn't enabled, the whole feature is inert for that account. *Gate for Phase 3.*
2. **Expired-contract historical availability + retention depth** (discovery §7.3). Can the endpoint return candles for an already-expired token? Needed for `near_prev` and historical `specific` months. Determine the retention window. *Gate for Phase 2/3 usefulness and Phase 5.*
3. **`_validate_ticker_token` on expired/thin contracts** (discovery §3 caveat, §7.4; `data_fetcher.py:179-233`). It probes a 28-day `minute` window ending today; for an expired contract this may be empty. Confirm an empty-but-valid 200 is treated as pass (only `invalid token`/`TokenException` fail it). If empty responses fail, add a validation bypass or widen the probe window for expired selectors. *Gate for Phase 3.*
4. **True rate ceiling of the `oms` endpoint under multi-contract concurrency** (discovery §7.2). Undocumented; the Kite Connect documented historical limit is ~3 req/s but this is a different endpoint. Probe conservatively before enabling wide bundle fan-out. *Gate for Phase 4 default `requests_per_second`.*
5. **Authoritative `lot_size`/`tick_size`** (discovery §5, §7.5) — the bundled dump shows placeholder `1`. Do not surface lot_size as authoritative; if ever needed, pull from a fresh live instruments file. *Not a code gate — a "don't trust this field" note baked into §0.*
6. **Bundled-CSV staleness** (discovery §5, §7.8): bundled expiries end 2025-06-05 while today is 2026-09 — offline/bundled-only cannot resolve current near-month. Document that near-month resolution requires a fresh download/cache; make bundled last-resort only. *Documentation gate for Phase 3.*
7. **Custom `instrument_id_path` regression** (discovery §7.9): closed by §3.1, verified by tests 10–11. *Gate for Phase 1 acceptance.*

Do not hard-code MCX expiry-day conventions anywhere — always read the `Expiry` column verbatim (discovery §5: metals ~5th, energy ~19th, set by MCX circulars; NSE F&O differs entirely). This is a standing implementation rule, not a one-time check.

---

## Scope boundaries (what is deferred)

- **Equity/index F&O (NFO-FUT).** Structurally identical schema (`segment == NFO-FUT`, discovery §1.5) — the same `FullName`-group + `Expiry`-sort logic generalizes, and the `exchange`/`segment` params in §1 are the forward-compatible extension point — but NFO is **out of scope** for this pass. No NFO-specific code, tests, or expiry conventions (last-Thursday cadence) are implemented now.
- **Commodity options (MCX-OPT, CE/PE).** Explicitly deferred. The strike column and option-type discrimination are intentionally not surfaced; options rows are filtered out (§2.1). Forward-compat only.
- **Continuous / back-adjusted stitching.** Presented as an open decision (§6); initial feature ships per-contract (6a). Ratio/difference back-adjustment is a gated Phase 5, not a default.
- **Live wiring / real-network execution.** This plan and its tests stay fully mocked (discovery §6). The §9 live-verification items require a real enctoken and a permitted MCX account; they are verification gates performed out-of-band, not automated tests, and no live calls are added to the test suite.

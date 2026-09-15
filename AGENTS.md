# AGENTS.md

Orientation for AI coding agents (and new contributors) working in this repository. For user-facing usage, see [README.md](README.md). For contribution process and conventions, see [CONTRIBUTING.md](CONTRIBUTING.md). `CLAUDE.md` is a symlink to this file.

## What this project is

A Python library that fetches historical OHLC data from Zerodha Kite by automating the **web** login flow (user ID + password + TOTP) instead of using the paid Kite Connect API. It returns pandas DataFrames, resolves symbols to instrument tokens, fetches long date ranges as parallel chunks, rate-limits requests, and caches an encrypted auth token in the OS keyring.

Because it depends on Zerodha's unofficial web endpoints, the auth flow and historical endpoint (in `utils/config.py` defaults) are the most likely things to break if Zerodha changes their site.

## Repository layout

```
src/zerodha_data_fetcher/
  __init__.py            Public API exports, package metadata, refresh_instruments()
  core/
    data_fetcher.py      ZerodhaDataFetcher — main entry point; chunking, parallel fetch, retries
    auth.py              AuthenticationManager — token lifecycle, keyring storage, expiry
    token_generator.py   The actual login flow: login -> TOTP 2FA -> extract enctoken
    instrument_manager.py  Symbol <-> instrument-token resolution, search, validation
    rate_limiter.py      Token-bucket request pacer + RateLimitedThreadPoolExecutor
  utils/
    config.py            Config — loads env vars / .env, defaults, validation
    data_loader.py       Instrument CSV: download, cache with TTL, bundled fallback
    encryption.py        Fernet token encryption; key stored via secret_store
    secret_store.py      Keyring wrapper with a file fallback for headless hosts
    exceptions.py        Exception hierarchy (ZerodhaAPIError is the base)
    helpers.py           @retry_on_failure (backoff) and @execution_timer decorators
    logging_config.py    setup_logging() — console + rotating file handlers
    data/                Bundled instrument snapshot (Kite_Instrument_ID.csv, ~6.7 MB)
tests/                   pytest suite — fully mocked, no network/keyring access
```

## Public API

Exported from `zerodha_data_fetcher` (`__init__.py`): `ZerodhaDataFetcher`, `ZerodhaInstrumentManager`, `AuthenticationManager`, `RateLimitedThreadPoolExecutor`, `Config`, `setup_logging`, `refresh_instruments`, and the exceptions `ZerodhaAPIError`, `AuthenticationError`, `InvalidTickerError`, `DataFetchError`, `TokenExpiredError`.

To resolve a symbol to an instrument token, use `ZerodhaInstrumentManager.resolve_symbol()` (handles int/numeric-string tokens, `EXCHANGE:SYMBOL`, exact tradingsymbol/name, and a best-effort substring fallback). The old scrip-master helpers (`get_instrument_token`, `fetch_instrument_ids`) and the legacy top-level aliases (`fetchDataZerodha`, `fetchZerodhaID`, `getEncAuthToken`, `get_TOTP`) were removed in 1.3.0 — do not reintroduce them.

## Common commands

This project uses [uv](https://docs.astral.sh/uv/). All commands assume the repo root.

```bash
uv sync --all-extras        # install runtime + dev + docs dependencies
uv run pytest               # run the test suite (with coverage, per pyproject addopts)
uv run pytest --no-cov      # faster, no coverage
uv run pytest -k auth       # run a subset
uv run black .              # format (line length 88)
uv run flake8               # lint
uv run mypy src/            # type-check (disallow_untyped_defs is on)
```

Run `uv run black .`, `uv run flake8`, and `uv run pytest` before proposing a change as done — these are what CI checks.

## Testing

- Tests live in `tests/`, one module per source area. Shared fixtures are in `tests/conftest.py`.
- **Nothing hits the real Zerodha API, keyring, or network.** Auth, `requests`, encryption, instrument loading, and `time.sleep` are all monkeypatched/stubbed (see `conftest.py` fixtures such as the fake auth manager, response stubs, in-memory keyring, and the autouse fixture that disables retry sleeps).
- A `clear_zerodha_env` fixture strips `ZERODHA_*` env vars so a developer's real `.env` cannot leak into a test run.
- Add tests with any change; CI will not pass otherwise.

## CI/CD

`.github/workflows/`:

- **test.yml** — on every push and PR: `uv sync --all-extras` then `uv run pytest` on `ubuntu-latest` (single Python version).
- **publish.yml** — on a `v*.*.*` tag: runs the suite across Python 3.8–3.12, downloads a fresh instrument CSV into `utils/data/`, builds, and publishes to PyPI via OIDC trusted publishing.

Note the asymmetry: PR CI tests one Python version, but publish tests 3.8–3.12. Keep code compatible with Python 3.8 (the floor in `pyproject.toml`).

## Conventions

- **Formatting/lint:** Black, line length 88; flake8 config in `setup.cfg`. Type annotations required (mypy `disallow_untyped_defs`).
- **Branches:** `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `ci/` prefixes.
- **Commits:** Conventional Commits style, e.g. `feat: add input validation for TOTP secret`.
- **Pre-commit:** `.pre-commit-config.yaml` runs whitespace fixes, `detect-secrets` (baseline in `.secrets.baseline`), Black, and flake8. Run `pre-commit install` after setup.

## Gotchas

- **Credential safety is the top rule.** This library handles real credentials. Never commit user IDs, passwords, TOTP secrets, or tokens. Use placeholders (`"YOUR_USER_ID"`, the well-known test TOTP `JBSWY3DPEHPK3PXP`). Review `git diff --cached` before committing.
- **`.env` and `test.py` in the repo root are git-ignored and untracked** — local developer artifacts, not part of the package. A local `.env` may hold real credentials; never read it into output, commit it, or run `test.py` in automation (it tries to hit the live API and needs a real account).
- **`timeframe` is not validated** in `fetch_historical_data` — any string is forwarded to the API and fails server-side if unsupported. Valid values: `minute`, `3minute`, `5minute`, `15minute`, `30minute`, `60minute`, `day`, `week`.
- **`requests_per_second` is clamped to 1–10** (`Config.MIN/MAX_REQUESTS_PER_SECOND`); values outside the range are silently adjusted, not rejected.
- **The bundled instrument CSV is large (~6.7 MB)** and shipped in the wheel (`package-data` in `pyproject.toml`). The publish workflow refreshes it; locally it can be stale, which affects symbol lookups until the cache TTL expires or `refresh_instruments()` is called.
- **Running code outside tests touches the real OS keyring** and may prompt for keychain access on first use. Tests avoid this via an in-memory keyring fixture.
- **Credential storage goes through `utils/secret_store.py`, not `keyring` directly.** It tries the OS keyring and falls back to a JSON file (POSIX `0600`) **only** when no backend exists (headless Linux/containers/CI) — a present-but-failing keyring raises rather than silently writing to disk. Governed by `ZERODHA_TOKEN_STORE` (`auto`/`keyring`/`file`) and `ZERODHA_TOKEN_STORE_PATH`. Route any new credential reads/writes through `secret_store` so they stay deployable on headless hosts; tests patch `secret_store`, not `keyring`.
- **Generated/local paths** (`htmlcov/`, `.coverage`, `.pytest_cache/`, `.uv-cache/`, `.venv/`, `logs/`) are safe to delete and are recreated on demand.

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-09-15

### Added
- `ZerodhaInstrumentManager.resolve_symbol()` — the recommended way to turn user
  input into an instrument token. Handles integer/numeric-string tokens,
  `EXCHANGE:SYMBOL` syntax (e.g. `"BSE:INFY"`), exact `tradingsymbol` and full
  `name` matches (with NSE→BSE exchange preference), and a best-effort substring
  fallback. Follows the Kite instruments spec, where `exchange` + `tradingsymbol`
  is the reliable unique key (numeric tokens are reused across expiries).
- MCX commodity futures support: `get_futures_contracts()`, near/previous/next and
  specific-contract resolution, `on_stale` freshness policy,
  `fetch_futures_historical_data()`, `fetch_futures_bundle()`, and
  `fetch_futures_continuous()` (raw / ratio / diff back-adjusted stitching).

### Changed
- **Multi-threaded auth optimization.** `AuthenticationManager` now holds the
  decrypted token in a process-global in-memory cache keyed by user ID. The hot
  path returns straight from memory (no keyring read/decrypt per request), and
  double-checked locking guarantees that exactly one thread runs the login + 2FA
  flow when a token expires — instead of every concurrent request
  re-authenticating independently. This removes the request lag seen under
  concurrency when the cached token was stale.
- `ZerodhaDataFetcher` symbol resolution now routes through `resolve_symbol()`.
- `validate_symbol()` signature simplified to `(symbol, exchange=None)` (the
  meaningless `is_stock` flag was dropped).

### Removed
- **Breaking:** retired the legacy backward-compatibility API and the
  scrip-master lookup path that only served it: `get_instrument_token()`,
  `fetch_instrument_ids()`, the `equity_scrip_path`/`commodity_scrip_path`
  constructor arguments, and the top-level `fetchDataZerodha`, `fetchZerodhaID`,
  `getEncAuthToken`, and `get_TOTP` functions. Use `ZerodhaDataFetcher`,
  `ZerodhaInstrumentManager.resolve_symbol()`, and `ZerodhaTokenGenerator`
  directly instead.

## [1.2.0] - 2026-04-28

### Added
- CHANGELOG.md with full version history
- GitHub Issue Templates (bug report and feature request) using YAML forms
- Pull Request template with contributor checklist
- Pre-commit configuration with secret detection (`detect-secrets`), formatting (`black`), and linting (`flake8`)
- "Why This Project?" section in README for new visitors
- PyPI monthly downloads badge in README

### Changed
- Removed stale `uv.lock` entry from `.gitignore` (file is intentionally tracked for reproducible dev environments)

## [1.1.0] - 2026-04-28

### Added
- Contributing guide (CONTRIBUTING.md) with complete contributor workflow
- Code of Conduct (CODE_OF_CONDUCT.md) based on Contributor Covenant 2.1
- Security policy (SECURITY.md) with vulnerability reporting process
- `.env.template` for safe credential configuration
- README badges for PyPI version, Python versions, CI status, and license

### Changed
- Improved documentation and code readability for open-source release
- Hardened `.gitignore` to exclude IDE configs, keys, certificates, and databases
- Fixed file encodings for cross-platform compatibility

## [1.0.3] - 2026-04-07

### Fixed
- Python 3.8/3.9 incompatible type hint syntax (replaced `X | Y` with `Optional[X]`)
- License field format for older setuptools compatibility
- Publish workflow missing `contents: read` permission for OIDC

## [1.0.0] - 2025-06-28

### Added
- Initial public release
- `ZerodhaDataFetcher` class with parallel historical data fetching
- Automatic authentication flow with password, TOTP, and encrypted token caching
- OS keyring integration for secure token storage (Fernet AES-128-CBC + HMAC-SHA256)
- `ZerodhaInstrumentManager` with symbol lookup, search, and validation
- Instrument data caching with configurable TTL and bundled CSV fallback
- `RateLimitedThreadPoolExecutor` for API request pacing
- Strict and partial chunk failure modes for historical data fetching
- Runtime configuration overrides for multi-account workflows
- Structured logging with separate console and file formats
- Custom exception hierarchy (`ZerodhaAPIError`, `AuthenticationError`, `InvalidTickerError`, `DataFetchError`, `TokenExpiredError`)
- Backward-compatible legacy API functions (`fetchDataZerodha`, `fetchZerodhaID`, `getEncAuthToken`)
- GitHub Actions CI for tests on all pushes/PRs
- GitHub Actions publish workflow with PyPI OIDC Trusted Publishing
- Multi-Python version test matrix (3.8, 3.9, 3.10, 3.11, 3.12)

[1.2.0]: https://github.com/JayceeGupta/Zerodha-Data-Fetcher/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/JayceeGupta/Zerodha-Data-Fetcher/compare/v1.0.3...v1.1.0
[1.0.3]: https://github.com/JayceeGupta/Zerodha-Data-Fetcher/compare/v1.0.0...v1.0.3
[1.0.0]: https://github.com/JayceeGupta/Zerodha-Data-Fetcher/releases/tag/v1.0.0

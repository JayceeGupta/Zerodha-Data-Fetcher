# Contributing to Zerodha Data Fetcher

Thank you for your interest in contributing! Whether you're fixing a bug, adding a feature, improving documentation, or just asking a question — you're welcome here.

This guide covers everything you need to get started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [I Have a Question](#i-have-a-question)
- [How to Report a Bug](#how-to-report-a-bug)
- [How to Request a Feature](#how-to-request-a-feature)
- [Setting Up Your Development Environment](#setting-up-your-development-environment)
- [Making Your First Contribution](#making-your-first-contribution)
- [Code Style](#code-style)
- [Running Tests](#running-tests)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Credential Safety](#credential-safety)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Please report unacceptable behavior to `guptajayam47@gmail.com`.

---

## I Have a Question

Before opening an issue, please check:

1. The [README](README.md) — especially the Quick Start and Configuration sections
2. [Existing issues](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/issues) — your question may already be answered

If you still have a question, open a thread in [GitHub Discussions](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/discussions) rather than an issue. Discussions are for questions and general conversation; issues are for bugs and feature requests.

---

## How to Report a Bug

Use the **Bug Report** template when [opening a new issue](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/issues/new/choose). The template will guide you through providing:

- What you expected to happen
- What actually happened
- Your Python version, OS, and package version
- Any error traceback

> **Important:** Never include real Zerodha credentials (user ID, password, TOTP secret) in an issue. If a bug involves authentication, use dummy values like `"YOUR_USER_ID"` in your reproduction steps.

---

## How to Request a Feature

Use the **Feature Request** template when [opening a new issue](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/issues/new/choose). Describe:

- The problem you're trying to solve
- Your proposed solution
- Whether you'd be willing to implement it yourself

---

## Setting Up Your Development Environment

You do **not** need a real Zerodha account to contribute. All tests use mocked authentication — no network calls are made during testing.

### Prerequisites

- Python 3.8 or higher
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — the package manager this project uses

### Step-by-Step Setup

1. **Fork the repository** on GitHub, then clone your fork:

   ```bash
   git clone https://github.com/YOUR_USERNAME/Zerodha-Data-Fetcher.git
   cd Zerodha-Data-Fetcher
   ```

2. **Install all dependencies** (including dev and test tools):

   ```bash
   uv sync --all-extras
   ```

3. **Copy the environment template** (the test suite does not require real values here):

   ```bash
   cp .env.template .env
   ```

   The `.env` file is git-ignored. You can leave the placeholder values as-is for development and testing.

4. **Verify your setup** by running the tests:

   ```bash
   uv run pytest
   ```

   You should see all tests pass. If anything fails, please [open an issue](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/issues/new/choose).

---

## Making Your First Contribution

Not sure where to start? Look for issues labeled [`good first issue`](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/labels/good%20first%20issue) — these are small, well-defined tasks perfect for newcomers.

Issues labeled [`help wanted`](https://github.com/JayceeGupta/Zerodha-Data-Fetcher/labels/help%20wanted) are slightly more involved but still open for anyone.

---

## Code Style

This project uses [Black](https://black.readthedocs.io/) for formatting and [flake8](https://flake8.pycqa.org/) for linting.

**Before submitting a PR, run both:**

```bash
# Format code
uv run black .

# Check for style issues
uv run flake8
```

Configuration is in `pyproject.toml`:
- Black: line length 88, target Python 3.8+
- flake8: max line length 88 (matching Black)

Type annotations are encouraged. The project uses [mypy](https://mypy.readthedocs.io/) for type checking:

```bash
uv run mypy src/
```

---

## Running Tests

```bash
# Run all tests with coverage report
uv run pytest

# Run a specific test file
uv run pytest tests/test_data_fetcher.py

# Run tests matching a keyword
uv run pytest -k "auth"

# Run without coverage (faster)
uv run pytest --no-cov
```

Tests live in the `tests/` directory and use pytest. All tests are mocked — no real Zerodha API calls are made.

**Every pull request must:**
- Pass all existing tests
- Include new tests for any new functionality or bug fix

---

## Submitting a Pull Request

1. **Create a branch** from `main` with a descriptive name:

   ```bash
   git checkout -b feat/add-async-support
   # or
   git checkout -b fix/handle-invalid-totp-secret
   ```

   Branch naming convention:
   - `feat/` — new feature
   - `fix/` — bug fix
   - `docs/` — documentation only
   - `refactor/` — code restructuring with no behavior change
   - `test/` — test additions or improvements
   - `ci/` — CI/CD changes

2. **Make your changes**, writing tests as you go.

3. **Run the full test suite** and make sure everything passes:

   ```bash
   uv run pytest
   uv run black .
   uv run flake8
   ```

4. **Commit your changes** with a clear message:

   ```bash
   git commit -m "feat: add input validation for TOTP secret"
   ```

5. **Push your branch** and open a pull request on GitHub. The PR template will guide you through the description.

6. **Wait for review.** The maintainer will review your PR within a few days. CI must pass before a PR can be merged.

---

## Credential Safety

> **This is the most important rule.**

This library handles Zerodha authentication credentials. Please follow these rules when contributing:

- **Never commit real credentials.** This includes user IDs, passwords, TOTP secrets, auth tokens, or any sensitive values.
- **Use placeholders in tests and examples.** Use values like `"YOUR_USER_ID"`, `"test_password"`, `"JBSWY3DPEHPK3PXP"` (a well-known TOTP test secret).
- **The `.env` file is git-ignored.** Never force-add it to git.
- **Review your diff before committing.** Run `git diff --cached` to check staged changes.

If you accidentally commit real credentials, please [report it privately](SECURITY.md) immediately so we can rotate them.

---

Thank you for contributing! Every improvement, no matter how small, makes this project better for the entire community.

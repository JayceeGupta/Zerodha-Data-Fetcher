# Security Policy

## Supported Versions

Security updates are applied to the latest release line.

| Version | Supported |
| ------- | --------- |
| 1.1.x | Yes |
| 1.0.x | No |
| < 1.0 | No |

## Reporting a Vulnerability

Please do not open a public GitHub issue for security vulnerabilities.

Send a private report to `guptajayam47@gmail.com` with:

- A clear description of the issue
- Steps to reproduce it
- The affected package version
- Any proof-of-concept code, logs, or screenshots that help validate impact

You will receive an initial acknowledgment within 72 hours. We aim to provide a
status update within 7 days and will coordinate disclosure timing with you after
the issue is confirmed.

## Credential Exposure Guidance

This project handles Zerodha authentication material, so credential leaks need
immediate attention.

- Never include real Zerodha user IDs, passwords, TOTP secrets, tokens, cookie
  values, or keyring contents in a report.
- If exposure involves credentials committed to git, shared in logs, or posted
  in CI output, report it privately as soon as possible so rotation can begin.
- Revoke or rotate exposed secrets on the Zerodha side before sharing follow-up
  details where possible.
- Sanitize request or response captures before sending them. Replace secrets
  with placeholders such as `REDACTED`.

## Disclosure and Response Process

- We will investigate and validate the report privately.
- If a fix is required, we will prepare a patch and release it before public
  disclosure when practical.
- Reporters acting in good faith will be credited for responsible disclosure if
  they want public acknowledgment.

## Out of Scope

The following are generally not treated as security vulnerabilities for this
project:

- Requests for help recovering lost credentials
- Reports based only on outdated dependencies without a demonstrated project
  impact
- Issues requiring public disclosure of active secrets

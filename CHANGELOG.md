# Changelog

## 0.1.0 — 2026-11-07

First release. Extracted from a private automation repository where the
1Password path had run daily for a year.

- `.env` files whose values may be `{{ scheme://… }}` references.
- Resolvers: `op://` (1Password, via the `op` CLI with a cached session and
  Touch ID sign-in, or via a service account), `keychain://` (macOS Keychain),
  `file://`, `env://`.
- Third-party resolvers through the `envref.resolvers` entry-point group.
- CLI: `envref run`, `export`, `check`, `doctor`, `op save-password`.

# envref

A `.env` where any value can be a reference into a secret store, resolved
when the file is loaded.

```dotenv
# .env
ATTIO_KEY={{ op://work/Attio/api_key }}          # 1Password
DB_PASSWORD={{ keychain://myapp/postgres }}      # macOS Keychain
TLS_KEY={{ file://~/.ssh/server.pem }}           # a file's contents
GITHUB_TOKEN={{ env://GH_TOKEN }}                # another variable
REGION=eu-north-1                                # a plain literal
```

```bash
envref run -- python app.py       # app.py sees ATTIO_KEY=<the real key>
```

```python
import envref
envref.load(".env")               # same thing, into os.environ
```

The file holds no secrets, so it can be committed. The scheme of each
reference picks the backend. Four ship built in, and your own takes one class
and one entry point.

## Why

`op run`, `berglas exec`, `chamber exec` and friends each do this for one
store. Teams rarely have one store. A laptop has 1Password and Keychain, a
container has a service account, a CI job has its own vault, and the same
`.env` should work in all three with the same names. `envref` keeps the file
format (plain dotenv, plus `{{ scheme://… }}`), and makes the backend a plugin.

## Install

```bash
uv tool install envref            # CLI
pip install envref                # library, zero dependencies
pip install 'envref[op]'          # + 1Password service-account support (SDK)
```

The `op://` CLI path needs only the [`op`](https://developer.1password.com/docs/cli/)
binary on PATH, no extra.

## Resolvers

| Scheme | Resolves to | Needs |
| --- | --- | --- |
| `op://vault/item/field` | a 1Password field | `op` CLI, or `OP_SERVICE_ACCOUNT_TOKEN` + `envref[op]` |
| `keychain://service/account` | a macOS Keychain generic password | macOS |
| `file://path` | the file's contents, one trailing newline dropped | — |
| `env://NAME` | another environment variable | — |

A value written as `{{ scheme://… }}` is always a reference, and an unknown
scheme is an error. A bare `scheme://…` without braces is resolved only when a
resolver for that scheme is installed, so `URL=https://example.com` stays a
literal and `KEY=op://vault/item/field` still works for files written for
`op read`.

### 1Password in detail

Two modes, chosen by the environment:

- **Service account** when `OP_SERVICE_ACCOUNT_TOKEN` is set. The SDK resolves
  every reference in one round trip. No binary, no biometrics. For containers.
- **CLI** otherwise. Every reference goes through one `op inject`. If `op` has
  no session, `envref` signs in: the account password comes from Keychain
  behind Touch ID if you stored it with `envref op save-password`, or from the
  terminal if not. The session token is cached in `~/.cache/envref/` so a
  burst of commands costs one sign-in; concurrent processes share it through
  a lock. See [SECURITY.md](SECURITY.md) for what that cache means.

Session caching presumes "biometric unlock for the CLI" is off in the
1Password app. With it on, `op` prompts per invocation and `envref` holds no
token.

Knobs: `OP_ACCOUNT` (shorthand, when several accounts are signed in),
`ENVREF_OP_SESSION_TTL` (seconds, default 1500, `0` disables the cache),
`ENVREF_OP_KEYCHAIN_SERVICE` / `ENVREF_OP_KEYCHAIN_ACCOUNT` (where the
password is stored, default `envref-op` / the account's email).

## CLI

```bash
envref run [-f FILE]... [--override] -- cmd args   # exec cmd with the resolved environment
envref export [-f FILE]... [--format shell|dotenv|json]
envref check [-f FILE]...                          # resolve and report per key; never prints a value
envref doctor                                      # installed resolvers and whether each can run here
envref op save-password [--account SHORTHAND]      # store the 1Password password in Keychain for Touch ID sign-in
```

`-f` repeats. The first file to set a name wins, so `-f .env.refs -f .env`
lets a local `.env` fill in what the shared references file lacks without
overriding it. Default is `.env`.

## Library

```python
import envref

values = envref.load(".env.refs", ".env")        # dict, also exported into os.environ
values = envref.load(".env", export=False)       # dict only
envref.load(".env", override=True)               # let the file win over existing variables

entries = envref.parse(text)                     # list[Entry], refs identified
envref.resolve(entries, registry={"op": ...})    # bring your own resolvers
```

Errors are typed: `UnknownScheme`, `ResolverUnavailable` (the backend cannot
run here: no `op`, not macOS, no token) and `ResolveError` (which references
failed and why, in `.failures`). All derive from `EnvrefError`.

## Writing a resolver

```python
# myenvref/aws.py
class SecretsManagerResolver:
    scheme = "awssm"

    def resolve(self, refs: list[str]) -> dict[str, str]:
        # refs are every awssm:// reference in the file, deduplicated: batch them.
        ...
        return {ref: value for ref, value in ...}

    def doctor(self) -> str:          # optional, shown by `envref doctor`
        return "ok"
```

```toml
# pyproject.toml
[project.entry-points."envref.resolvers"]
awssm = "myenvref.aws:SecretsManagerResolver"
```

Installed next to `envref`, `{{ awssm://… }}` now resolves. An entry point
with a built-in's name replaces it.

## Prior art

[`teller`](https://github.com/tellerops/teller) and
[`novops`](https://github.com/PierreBeucher/novops) are multi-provider too,
with the mapping in a YAML config rather than inline in the `.env`.
[`berglas`](https://github.com/GoogleCloudPlatform/berglas) has inline
`sm://` references, for Google Cloud only. [`dotenvx`](https://dotenvx.com)
encrypts the values rather than referencing them. `op inject` is what the
`{{ }}` syntax comes from, and any `.env.op` written for it is a valid
`envref` file.

## Status

Extracted in November 2026 from a private automation repository where the
1Password path had run daily for a year, on a laptop and in scheduled
containers. The other resolvers are new. macOS and Linux; Keychain and Touch
ID are macOS only.

MIT.

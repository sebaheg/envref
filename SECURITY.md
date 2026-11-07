# Security

## Threat model

`envref` moves secrets from a store into a process's environment. It never
stores a secret itself, with one deliberate exception described below. What
you should know before trusting it:

**The file is not secret.** An `.env` of references holds the names of your
vaults and items, which is an inventory of what you use. Treat it like source
code: fine in a private repository, think twice in a public one.

**Resolved values live in the environment of the process you start.** Any
child process inherits them, and on most systems any process running as the
same user can read another process's environment. This is true of every
secrets-to-env tool; `envref` adds nothing and removes nothing here.

**The 1Password CLI resolver caches a session token.** With "biometric unlock
for the CLI" turned off in 1Password, `op signin` returns a session token that
is good for about 30 minutes of inactivity. `envref` writes it to
`$XDG_CACHE_HOME/envref/op-session.json` (default `~/.cache/envref/`), mode
0600, and re-uses it so a burst of commands costs one sign-in rather than one
per command. The trade: during that window, any process running as your user
can read the token and, with it, every item the account can see, with no
Touch ID. If that is unacceptable for your machine, set
`ENVREF_OP_SESSION_TTL=0` to disable the cache, or turn biometric CLI unlock
on in 1Password, in which case `op` prompts per invocation and `envref` never
holds a token.

**The 1Password account password may live in macOS Keychain.** `envref op
save-password` stores it as a generic password item, so that an expired
session can be renewed without typing. Reading it goes through a small Swift
helper that requires Touch ID (`LAContext`, biometrics only) before calling
`security find-generic-password`. Without Touch ID hardware, or without
`swiftc`, the read falls back to `security` alone, which shows the system's
own authorisation dialog. The helper is compiled from source on first use
into the cache directory; it is not shipped as a binary.

**The service-account path holds a bearer token in the environment.** That is
how 1Password service accounts work. Scope the account to one vault that holds
only what the job needs, so a leaked token reads five items rather than every
credential you own. `envref` fails loudly when a reference points outside the
granted vault rather than falling back to another method.

**Resolvers are code.** A third-party resolver installed through the
`envref.resolvers` entry point runs with your privileges and sees every
reference of its scheme. Install resolvers the way you install any dependency.

## Reporting

Open a private security advisory on GitHub, or email the address on the
author's GitHub profile. Please do not open a public issue for a vulnerability.

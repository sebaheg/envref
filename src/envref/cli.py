"""`envref` command line: run a command with references resolved, export them,
check a file without printing values, inspect the backends."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import sys
from pathlib import Path

from envref import __version__
from envref.core import EnvrefError, ResolveError, load, resolve
from envref.parse import parse_file


def _files(args: argparse.Namespace) -> list[str]:
    return args.file or [".env"]


def cmd_run(args: argparse.Namespace) -> int:
    if not args.command:
        print("envref run: no command given (use `envref run -- cmd args`)", file=sys.stderr)
        return 2
    env = dict(os.environ)
    load(*_files(args), override=args.override, environ=env)
    os.execvpe(args.command[0], args.command, env)
    return 0  # unreachable


def cmd_export(args: argparse.Namespace) -> int:
    values = load(*_files(args), export=False)
    if args.format == "json":
        print(json.dumps(values, indent=2))
    elif args.format == "dotenv":
        for name, value in values.items():
            print(f"{name}={json.dumps(value)}")
    else:
        for name, value in values.items():
            print(f"export {name}={shlex.quote(value)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Resolve everything and report per key, never printing a value."""
    from envref.resolvers import registry

    resolvers = registry()
    failed = False
    for file in _files(args):
        path = Path(file).expanduser()
        if not path.exists():
            print(f"{file}: not found")
            failed = True
            continue
        entries = parse_file(path)
        print(f"{file}: {len(entries)} entries")
        try:
            resolve(entries, registry=resolvers)
            failures: dict[str, str] = {}
        except ResolveError as exc:
            failures = exc.failures
            failed = True
        except EnvrefError as exc:
            print(f"  error: {exc}")
            failed = True
            continue
        for entry in entries:
            if entry.ref is None or entry.scheme not in resolvers:
                kind = "literal"
                mark = "·"
            else:
                kind = f"{entry.scheme}://"
                mark = "✗" if entry.ref in failures else "✓"
            line = f"  {mark} {entry.name:<40} {kind}"
            if entry.ref in failures:
                line += f"  {failures[entry.ref]}"
            print(line)
    return 1 if failed else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from envref.resolvers import registry

    print(f"envref {__version__}")
    for scheme, resolver in sorted(registry().items()):
        status = resolver.doctor() if hasattr(resolver, "doctor") else "ok"
        print(f"  {scheme + '://':<12} {type(resolver).__module__}.{type(resolver).__name__}  {status}")
    return 0


def cmd_op_save_password(args: argparse.Namespace) -> int:
    from envref.resolvers import op

    account = args.account or op.resolve_account()
    if not account:
        print("no 1Password account found; pass --account <shorthand>", file=sys.stderr)
        return 1
    password = getpass.getpass(f"1Password account password for {account}: ")
    if not password:
        return 1
    service, name = op.save_password(account, password)
    print(f"Stored in Keychain as service={service} account={name}.")
    print("envref will read it behind Touch ID when a session needs renewing.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="envref",
        description="A .env where any value can be a reference into a secret store.",
    )
    parser.add_argument("--version", action="version", version=f"envref {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_files(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "-f", "--file", action="append", metavar="FILE",
            help="env file to load; repeat for several, first to set a name wins (default .env)",
        )

    run = sub.add_parser("run", help="run a command with the resolved environment")
    add_files(run)
    run.add_argument("--override", action="store_true", help="let the file override existing variables")
    run.add_argument("command", nargs=argparse.REMAINDER, help="command and arguments, after --")
    run.set_defaults(func=cmd_run)

    export = sub.add_parser("export", help="print the resolved variables")
    add_files(export)
    export.add_argument("--format", choices=["shell", "dotenv", "json"], default="shell")
    export.set_defaults(func=cmd_export)

    check = sub.add_parser("check", help="resolve every reference and report, without printing values")
    add_files(check)
    check.set_defaults(func=cmd_check)

    doctor = sub.add_parser("doctor", help="list installed resolvers and whether each can run here")
    doctor.set_defaults(func=cmd_doctor)

    op = sub.add_parser("op", help="1Password helpers")
    op_sub = op.add_subparsers(dest="op_cmd", required=True)
    save = op_sub.add_parser(
        "save-password", help="store the account password in macOS Keychain for Touch ID sign-in"
    )
    save.add_argument("--account", help="account shorthand (default: the only signed-in account)")
    save.set_defaults(func=cmd_op_save_password)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]
    try:
        code = args.func(args)
    except EnvrefError as exc:
        print(f"envref: {exc}", file=sys.stderr)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()

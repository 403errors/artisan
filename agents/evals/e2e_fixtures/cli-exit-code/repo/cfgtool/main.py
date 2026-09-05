"""cfgtool — validates INI-style config files."""

import argparse
import configparser
import sys

REQUIRED_SECTIONS = ("server", "logging")


def check_config(path: str) -> list[str]:
    """Returns the list of problems with the config file (empty when valid)."""
    parser = configparser.ConfigParser()
    try:
        with open(path) as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        return [f"cannot parse: {exc}"]
    return [f"missing section: {s}" for s in REQUIRED_SECTIONS if not parser.has_section(s)]


def cmd_check(args: argparse.Namespace) -> int:
    problems = check_config(args.path)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        return 0
    print(f"OK: {args.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfgtool")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate a config file")
    check.add_argument("path")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

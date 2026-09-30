"""jarvis auth <credentials.json> [--out token.json] | jarvis run | jarvis reindex"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jarvis")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth", help="one-time OAuth consent (needs a browser); writes token.json")
    a.add_argument("credentials", type=Path)
    a.add_argument("--out", type=Path, default=Path("token.json"))
    sub.add_parser("run", help="one pipeline pass against the configured data dir")
    sub.add_parser("reindex", help="drop and rebuild the search index from the archive")
    args = p.parse_args(argv)

    if args.cmd == "auth":
        from jarvis.sources.gmail import run_consent_flow

        scopes = run_consent_flow(args.credentials, args.out)
        print(f"wrote {args.out} with scopes: {scopes}")
        return 0

    from jarvis.pipeline import build_runtime

    rt = build_runtime()
    if args.cmd == "run":
        s = rt.run_once()
        print(s.model_dump_json())
        return 0 if s.errors == 0 else 1
    if args.cmd == "reindex":
        print(f"indexed {rt.index.rebuild()} messages")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

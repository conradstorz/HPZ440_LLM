"""obiwan scan | reindex | status | confirm <subject_id> | forget <subject_id> --reason R

Runs inside the obiwan container (docker compose exec), where all three credentials are in the environment. The
commander credential exists only there and in the Commander's own hands: Jarvis's container never receives it."""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def _transport() -> httpx.BaseTransport | None:
    return None  # tests replace this with a MockTransport


def _call(method: str, path: str, *, token_var: str, body: dict | None = None) -> int:
    base = os.environ.get("OBIWAN_BASE_URL", "http://localhost:8070").rstrip("/")
    token = os.environ.get(token_var, "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=600.0, transport=_transport()) as client:
        resp = client.request(method, f"{base}{path}", headers=headers, json=body)
    if resp.status_code >= 400:
        print(f"HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1
    print(json.dumps(resp.json(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="obiwan")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="scan every configured root and the inbox, then drain pending work")
    sub.add_parser("reindex", help="drop and rebuild the search projection from stored chunks")
    sub.add_parser("status", help="roots, counts, pending, failed, last scan")
    c = sub.add_parser("confirm", help="Commander only: promote a relayed record to direct")
    c.add_argument("subject_id")
    f = sub.add_parser("forget", help="Commander only: tombstone a subject")
    f.add_argument("subject_id")
    f.add_argument("--reason", required=True)
    call_p = sub.add_parser("call", help="make one HTTP call with a role's credential (operators; replaces curl)")
    call_p.add_argument("method")
    call_p.add_argument("path")
    call_p.add_argument("--role", choices=["reader", "writer", "commander"], default="reader")
    call_p.add_argument("--json", dest="json_body", default=None)
    args = p.parse_args(argv)
    if args.cmd == "scan":
        return _call("POST", "/scan", token_var="OBIWAN_WRITER_TOKEN")
    if args.cmd == "reindex":
        return _call("POST", "/reindex", token_var="OBIWAN_WRITER_TOKEN")
    if args.cmd == "status":
        return _call("GET", "/status", token_var="OBIWAN_READER_TOKEN")
    if args.cmd == "confirm":
        return _call("POST", "/confirm", token_var="OBIWAN_COMMANDER_TOKEN", body={"subject_id": args.subject_id, "action": "promote"})
    if args.cmd == "forget":
        return _call("POST", "/confirm", token_var="OBIWAN_COMMANDER_TOKEN",
                     body={"subject_id": args.subject_id, "action": "forget", "reason": args.reason})
    if args.cmd == "call":
        body = json.loads(args.json_body) if args.json_body is not None else None
        return _call(args.method.upper(), args.path, token_var=f"OBIWAN_{args.role.upper()}_TOKEN", body=body)
    return 2


if __name__ == "__main__":
    sys.exit(main())

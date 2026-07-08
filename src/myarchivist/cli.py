from __future__ import annotations

import argparse
import json
from pathlib import Path

from mythings.engine import ClaudeCLIEngine, Engine, NoopEngine
from mythings.ledger import Ledger

from myarchivist.archivist import Archivist

_ENGINE_NAMES = ("noop", "claude-cli")


def build_engine(name: str, *, model: str | None = None) -> Engine:
    if name == "claude-cli":
        return ClaudeCLIEngine(model=model)
    return NoopEngine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="myarchivist",
        description="Catalog a personal book/materials collection (physical + digital).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="scan digital/physical holdings and refresh the catalog")
    scan.add_argument(
        "--digital", action="append", default=[], help="a directory to scan (repeatable)"
    )
    scan.add_argument("--physical", help="a CSV of physical intake rows")
    scan.add_argument("--repo", help="GitHub slug owner/name")
    scan.add_argument(
        "--source", type=Path, default=Path.cwd(), help="local checkout to write into"
    )
    scan.add_argument("--base", default="main")
    scan.add_argument("--issue", type=int, help="also comment the refreshed catalog on this issue")
    scan.add_argument("--no-pr", action="store_true")
    scan.add_argument("--no-comment", action="store_true")
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    scan.add_argument("--engine", choices=sorted(_ENGINE_NAMES), default="noop")
    scan.add_argument("--engine-model", help="model for --engine claude-cli")

    args = parser.parse_args(argv)
    engine = build_engine(args.engine, model=args.engine_model)

    archivist = Archivist(
        source=args.source,
        ledger=Ledger(args.ledger),
        repo=args.repo,
        base=args.base,
        engine=engine,
    )
    result = archivist.scan(
        digital=args.digital,
        physical=args.physical,
        issue=args.issue,
        no_pr=args.no_pr,
        no_comment=args.no_comment,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "outcome": result.outcome,
                    "new_entries": result.new_entries,
                    "detail": result.detail,
                    "pr": result.pr,
                    "comment_url": result.comment_url,
                }
            )
        )
    else:
        print(f"{result.outcome}: {result.detail}")
    return 0 if result.outcome != "failure" else 1


if __name__ == "__main__":
    raise SystemExit(main())

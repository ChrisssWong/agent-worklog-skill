"""Machine-readable CLI. All commands use an explicit data root."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .core import WorklogError, all_revisions, capture, close_day, effective, load_policy, validate_event
from .reports import build, report


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="worklog")
    p.add_argument("--data", type=Path, required=True, help="dedicated data directory")
    p.add_argument("--dry-run", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("candidate", type=Path)
    close = sub.add_parser("close-day")
    close.add_argument("--agent", required=True)
    close.add_argument("--date", required=True)
    close.add_argument("--scope", required=True)
    agg = sub.add_parser("aggregate")
    agg.add_argument("kind", choices=["daily", "agent_daily", "weekly", "monthly", "quarterly", "yearly"])
    agg.add_argument("key")
    agg.add_argument("--agent")
    agg.add_argument("--as-of", required=True, help="ISO datetime with offset")
    val = sub.add_parser("validate")
    val.add_argument("scope", choices=["raw", "reports", "policy", "all"], default="all")
    stat = sub.add_parser("status")
    stat.add_argument("--date", required=True)
    syn = sub.add_parser("sync")
    syn.add_argument("--remote", default="origin")
    syn.add_argument("--branch", default="main")
    due = sub.add_parser("run-due")
    due.add_argument("--as-of", required=True)
    dash = sub.add_parser("dashboard")
    dash.add_argument("--as-of", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.data.resolve()
    try:
        if args.command == "import":
            candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
            result = capture(root, candidate, args.dry_run)
        elif args.command == "close-day":
            result = close_day(root, args.agent, args.date, args.scope, args.dry_run)
        elif args.command == "aggregate":
            as_of = datetime.fromisoformat(args.as_of)
            if as_of.utcoffset() is None:
                raise WorklogError("AS_OF_OFFSET_REQUIRED")
            if args.dry_run:
                result = build(root, args.kind, args.key, as_of, args.agent, True)
            else:
                from .orchestrate import aggregator_lock
                with aggregator_lock(root):
                    result = build(root, args.kind, args.key, as_of, args.agent)
        elif args.command == "validate":
            policy = load_policy(root)
            revisions = all_revisions(root)
            if args.scope in ("raw", "all"):
                for item in revisions:
                    validate_event(item, policy["timezone"])
                _, conflicts = effective(revisions)
            else:
                conflicts = []
            if args.scope in ("reports", "all"):
                from .core import validate_shape
                for path in (root / "reports").rglob("*.json"):
                    validate_shape(json.loads(path.read_text(encoding="utf-8")), "report")
            result = {"valid": not conflicts, "raw_revisions": len(revisions), "conflicts": conflicts}
        elif args.command == "sync":
            from .git_sync import sync
            result = sync(root, args.remote, args.branch, args.dry_run)
        elif args.command == "run-due":
            from .orchestrate import run_due
            as_of = datetime.fromisoformat(args.as_of)
            if as_of.utcoffset() is None:
                raise WorklogError("AS_OF_OFFSET_REQUIRED")
            result = run_due(root, as_of, args.dry_run)
        elif args.command == "dashboard":
            from .dashboard import build_dashboard
            from .orchestrate import aggregator_lock
            as_of = datetime.fromisoformat(args.as_of)
            if as_of.utcoffset() is None:
                raise WorklogError("AS_OF_OFFSET_REQUIRED")
            if args.dry_run:
                result = build_dashboard(root, as_of, True)
            else:
                with aggregator_lock(root):
                    result = build_dashboard(root, as_of)
                    from .publish import publish
                    result["published"] = publish(root)
        else:
            value = report(root, "daily", args.date, datetime.now().astimezone())
            result = {"report_key": value["report_key"], "lifecycle": value["lifecycle"], "completeness": value["completeness"], "coverage": value["coverage"], "metrics": value["metrics"]}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.command == "aggregate" and result["completeness"] == "incomplete":
            return 4
        if args.command == "sync" and result["sync"] == "pending":
            return 5
        if args.command == "sync" and result["sync"] == "conflict":
            return 6
        return 0
    except WorklogError as exc:
        print(json.dumps({"error": exc.code, "recoverable": exc.exit_code in (4, 5, 6, 7)}, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": "INPUT_OR_IO_FAILED", "recoverable": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

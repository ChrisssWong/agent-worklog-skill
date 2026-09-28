#!/usr/bin/env python3
"""launchd entrypoint for this machine. No credentials or external service."""
from datetime import datetime
import json
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[1]
DATA = SKILL.parent / "agent-worklog-data"
sys.path.insert(0, str(SKILL / "src"))

from worklog.git_sync import sync  # noqa: E402
from worklog.orchestrate import run_due  # noqa: E402
from worklog.core import WorklogError  # noqa: E402

if __name__ == "__main__":
    (DATA / ".worklog-runtime").mkdir(exist_ok=True)
    now = datetime.now().astimezone()
    try:
        result = run_due(DATA, now)
        result["git"] = sync(DATA, allowed_prefixes=("reports/", "manifests/", "metrics/", "site/", "analysis/"))
        result["run_at"] = now.isoformat()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except WorklogError as exc:
        print(json.dumps({"run_at": now.isoformat(), "error": exc.code}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(exc.exit_code)
    except Exception:
        print(json.dumps({"run_at": now.isoformat(), "error": "INTERNAL_FAILED"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(8)

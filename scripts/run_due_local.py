#!/usr/bin/env python3
"""launchd entrypoint for this machine. No credentials or external service."""
from datetime import datetime
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[1]
DATA = SKILL.parent / "agent-worklog-data"
sys.path.insert(0, str(SKILL / "src"))

from worklog.cli import main  # noqa: E402

if __name__ == "__main__":
    (DATA / ".worklog-runtime").mkdir(exist_ok=True)
    raise SystemExit(main(["--data", str(DATA), "run-due", "--as-of", datetime.now().astimezone().isoformat()]))

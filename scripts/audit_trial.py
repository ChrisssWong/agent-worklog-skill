#!/usr/bin/env python3
"""Summarize seven actual calendar days of local scheduled runs."""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
DATA = SKILL.parent / "agent-worklog-data"
RUNTIME = DATA / ".worklog-runtime"


def read_json_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
            if "run_at" in value:
                result.append(value)
        except json.JSONDecodeError:
            continue
    return result


def main() -> None:
    successes = read_json_lines(RUNTIME / "launchd.out.log")
    errors = read_json_lines(RUNTIME / "launchd.err.log")
    by_day = defaultdict(list)
    for item in successes:
        by_day[date.fromisoformat(item["run_at"][:10])].append(item)
    if not successes:
        result = {"status": "not_started", "days_with_runs": 0, "errors": len(errors)}
    else:
        first = min(by_day)
        last = first + timedelta(days=6)
        today = datetime.now().astimezone().date()
        days = [(first + timedelta(days=i)).isoformat() for i in range(7)]
        missing = [d for d in days if date.fromisoformat(d) not in by_day]
        incomplete = []
        for day_text in days:
            day = date.fromisoformat(day_text)
            daily_path = DATA / "reports" / day.strftime("%Y/daily/%m/%d/summary.json")
            if today > day and not daily_path.exists():
                incomplete.append(f"missing_daily:{day_text}")
            if day.weekday() == 6 and today > day:
                iso = day.isocalendar()
                weekly_path = DATA / "reports" / str(iso.year) / "weekly" / f"W{iso.week:02d}" / "summary.json"
                if not weekly_path.exists():
                    incomplete.append(f"missing_weekly:{iso.year}-W{iso.week:02d}")
        for path in (DATA / "reports").rglob("*.json"):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                if report.get("kind") not in ("daily", "weekly"):
                    continue
                start = date.fromisoformat(report["period"]["start"][:10])
                end = date.fromisoformat(report["period"]["end"][:10])
                if start <= last and end > first and report["completeness"] != "complete":
                    incomplete.append(report["report_key"])
            except (json.JSONDecodeError, KeyError, ValueError):
                incomplete.append(f"invalid:{path.name}")
        incomplete.sort()
        trial_errors = [e for e in errors if first <= date.fromisoformat(e["run_at"][:10]) <= last]
        result = {"status": "ready_for_review" if today > last and not missing and not trial_errors and not incomplete else "in_progress_or_incomplete", "first_day": first.isoformat(), "seventh_day": last.isoformat(), "days_with_runs": sum(date.fromisoformat(d) in by_day for d in days), "missing_days": missing, "errors": len(trial_errors), "incomplete_reports": incomplete}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

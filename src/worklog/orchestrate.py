"""Local single-writer orchestration. An external scheduler only wakes run_due."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import WorklogError, load_policy, timestamp
from .reports import build


@contextmanager
def aggregator_lock(root: Path):
    runtime = root / ".worklog-runtime"
    runtime.mkdir(exist_ok=True)
    path = runtime / "aggregator.lock"
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorklogError("AGGREGATOR_BUSY", 7) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def due_keys(root: Path, as_of: datetime) -> list[tuple[str, str]]:
    policy = load_policy(root)
    local = as_of.astimezone(ZoneInfo(policy["timezone"]))
    start = min(date.fromisoformat(a["enabled_from"]) for a in policy["agents"])
    end = local.date()
    planned = []
    day = start
    close_hour, close_minute = map(int, policy["schedule"]["close_time"].split(":"))
    provisional_hour, provisional_minute = map(int, policy["schedule"]["provisional_time"].split(":"))
    while day <= end:
        ready = local >= datetime.combine(day + timedelta(days=1), time(close_hour, close_minute), local.tzinfo)
        provisional = day == end and local >= datetime.combine(day, time(provisional_hour, provisional_minute), local.tzinfo)
        if ready or provisional:
            planned.append(("daily", day.isoformat()))
        day += timedelta(days=1)
    closed_days = [date.fromisoformat(key) for kind, key in planned if kind == "daily" and date.fromisoformat(key) < end]
    weeks = {(d.isocalendar().year, d.isocalendar().week) for d in closed_days if d.weekday() == 6}
    for year, week in sorted(weeks):
        planned.append(("weekly", f"{year}-W{week:02d}"))
    for d in closed_days:
        if (d + timedelta(days=1)).month != d.month:
            planned.append(("monthly", d.strftime("%Y-%m")))
            if d.month in (3, 6, 9, 12):
                planned.append(("quarterly", f"{d.year}-Q{(d.month - 1) // 3 + 1}"))
            if d.month == 12:
                planned.append(("yearly", str(d.year)))
    return planned


def run_due(root: Path, as_of: datetime, dry_run: bool = False, force: bool = False) -> dict:
    if dry_run:
        return _run_due_inner(root, as_of, True, force)
    with aggregator_lock(root):
        return _run_due_inner(root, as_of, False, force)


def _run_due_inner(root: Path, as_of: datetime, dry_run: bool, force: bool) -> dict:
    planned = due_keys(root, as_of)
    runtime = root / ".worklog-runtime"
    state_path = runtime / "build-state.json"
    prior = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"inputs": {}, "reports": {}}
    policy = load_policy(root)
    zone = ZoneInfo(policy["timezone"])
    inputs = {}
    for folder in ("raw", "coverage", "policy", "overrides"):
        for path in (root / folder).rglob("*.json") if folder != "policy" else (root / folder).rglob("*.yaml"):
            relative = str(path.relative_to(root))
            item = {"hash": hashlib.sha256(path.read_bytes()).hexdigest(), "days": [], "task_state": False}
            if folder == "raw":
                raw = json.loads(path.read_text(encoding="utf-8"))
                days = {raw["work_date"]}
                for seg in raw["time"]["segments"]:
                    days.add(timestamp(seg["start"]).astimezone(zone).date().isoformat())
                if raw["task_state_event"] is not None:
                    days.add(timestamp(raw["task_state_event"]["occurred_at"]).astimezone(zone).date().isoformat())
                    item["task_state"] = True
                item["days"] = sorted(days)
            elif folder == "coverage":
                item["days"] = [json.loads(path.read_text(encoding="utf-8"))["work_date"]]
            inputs[relative] = item
    skill_root = Path(__file__).resolve().parents[2]
    for path in sorted((skill_root / "src/worklog").glob("*.py")) + sorted((skill_root / "templates").glob("*.html")):
        inputs[f"skill/{path.relative_to(skill_root)}"] = {"hash": hashlib.sha256(path.read_bytes()).hexdigest(), "days": []}
    changed_paths = {path for path in set(inputs) | set(prior["inputs"]) if inputs.get(path) != prior["inputs"].get(path)}
    policy_changed = any(path.startswith(("policy/", "overrides/", "skill/")) for path in changed_paths)
    changed_days = set()
    state_changed_days = set()
    for path in changed_paths:
        for state in (inputs, prior["inputs"]):
            changed_days.update(state.get(path, {}).get("days", []))
            if state.get(path, {}).get("task_state"):
                state_changed_days.update(state[path].get("days", []))
    def affected(kind: str, key: str) -> bool:
        from .reports import period
        start, end, _ = period(kind, key, policy["timezone"])
        if any(start <= date.fromisoformat(day) < end for day in changed_days):
            return True
        return any(date.fromisoformat(day) < end for day in state_changed_days)
    selected = []
    for kind, key in planned:
        label = f"{kind}:{key}"
        previous = prior["reports"].get(label)
        if force or previous is None or policy_changed or affected(kind, key) or previous == "provisional":
            selected.append((kind, key))
    if dry_run:
        return {"due": [f"{kind}:{key}" for kind, key in selected], "changed_inputs": sorted(changed_paths), "dry_run": True}
    results = []
    with nullcontext():
        for kind, key in selected:
            results.append(build(root, kind, key, as_of))
        from .dashboard import build_dashboard
        from .publish import publish
        dashboard = build_dashboard(root, as_of) if selected or changed_paths or not (root / "site/index.html").exists() else {"changed": 0}
        published = publish(root) if dashboard["changed"] or any(x["changed"] for x in results) or not (root / "site/current").exists() else {"entry": str(root / "site/current/index.html"), "version": (root / "site/current").resolve().name}
        report_states = dict(prior["reports"])
        for item in results:
            report_states[item["report_key"]] = item["lifecycle"]
        runtime.mkdir(exist_ok=True)
        temp = state_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"inputs": inputs, "reports": report_states}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temp.replace(state_path)
    return {"due": len(selected), "changed": sum(x["changed"] for x in results) + dashboard["changed"], "incomplete": [x["report_key"] for x in results if x["completeness"] == "incomplete"], "published": published}

"""Report DAG. Numeric facts always merge by stable identity."""
from __future__ import annotations

import calendar
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import __version__
from .core import WorklogError, all_revisions, canonical, closure_digest, digest, effective, load_policy, revision_files, timestamp, validate_shape

TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "templates"


def period(kind: str, key: str, zone: str) -> tuple[date, date, str]:
    try:
        if kind in ("daily", "agent_daily"):
            start = date.fromisoformat(key)
            end = start + timedelta(days=1)
        elif kind == "weekly":
            year, week = key.split("-W")
            start = date.fromisocalendar(int(year), int(week), 1)
            end = start + timedelta(days=7)
        elif kind == "monthly":
            year, month = map(int, key.split("-"))
            start = date(year, month, 1)
            end = date(year + (month == 12), month % 12 + 1, 1)
        elif kind == "quarterly":
            year, quarter = key.split("-Q")
            start = date(int(year), (int(quarter) - 1) * 3 + 1, 1)
            end = date(int(year) + (int(quarter) == 4), (int(quarter) * 3) % 12 + 1, 1)
        elif kind == "yearly":
            start = date(int(key), 1, 1)
            end = date(int(key) + 1, 1, 1)
        else:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise WorklogError("PERIOD_INVALID") from exc
    return start, end, zone


def report_path(kind: str, key: str, agent_id: str | None = None) -> Path:
    if kind == "agent_daily":
        d = date.fromisoformat(key)
        return Path("reports") / d.strftime("%Y/daily/%m/%d/agents") / f"{agent_id}.json"
    if kind == "daily":
        d = date.fromisoformat(key)
        return Path("reports") / d.strftime("%Y/daily/%m/%d/summary.json")
    if kind == "weekly":
        y, w = key.split("-W")
        return Path("reports") / y / "weekly" / f"W{w}" / "summary.json"
    if kind == "monthly":
        y, m = key.split("-")
        return Path("reports") / y / "monthly" / m / "summary.json"
    if kind == "quarterly":
        y, q = key.split("-")
        return Path("reports") / y / "quarterly" / q / "summary.json"
    return Path("reports") / key / "yearly/summary.json"


def empty_facts() -> dict:
    return {"events": {}, "buckets": {}, "task_states": {}, "task_snapshot": {}}


def event_fact(event: dict) -> dict:
    return {key: event[key] for key in ("entry_id", "revision_id", "agent_id", "project_id", "task_id", "topic_id", "title", "summary", "status", "work_date", "category", "technologies", "outputs", "source_refs", "milestone", "time", "task_state_event")}


def daily_facts(events: list[dict], work_date: str, zone: str, agent_id: str | None = None) -> dict:
    facts = empty_facts()
    z = ZoneInfo(zone)
    for event in events:
        if agent_id is not None and event["agent_id"] != agent_id:
            continue
        if event["work_date"] == work_date:
            facts["events"][event["entry_id"]] = event_fact(event)
        state = event["task_state_event"]
        if state is not None and timestamp(state["occurred_at"]).astimezone(z).date().isoformat() == work_date:
            facts["task_states"][event["entry_id"]] = {"task_id": event["task_id"], "revision_id": event["revision_id"], **state}
        t = event["time"]
        if t["duration_seconds"] is None:
            continue
        if t["allocation_method"] == "work_date":
            if event["work_date"] == work_date:
                facts["buckets"][f"{event['entry_id']}:0"] = {"entry_id": event["entry_id"], "revision_id": event["revision_id"], "date": work_date, "duration_type": t["duration_type"], "seconds": t["duration_seconds"], "project_id": event["project_id"], "technologies": event["technologies"]}
        else:
            for index, seg in enumerate(t["segments"]):
                day = timestamp(seg["start"]).astimezone(z).date().isoformat()
                if day == work_date:
                    facts["buckets"][f"{event['entry_id']}:{index}"] = {"entry_id": event["entry_id"], "revision_id": event["revision_id"], "date": day, "duration_type": t["duration_type"], "seconds": seg["duration_seconds"], "project_id": event["project_id"], "technologies": event["technologies"]}
    return facts


def merge_facts(children: list[dict]) -> dict:
    merged = empty_facts()
    for child in children:
        for group in ("events", "buckets", "task_states"):
            for key, value in child["facts"][group].items():
                if key in merged[group] and merged[group][key] != value:
                    raise WorklogError("FACT_ID_CONFLICT", 6)
                merged[group][key] = value
    return {k: dict(sorted(v.items())) for k, v in merged.items()}


def metrics(facts: dict) -> dict:
    events = list(facts["events"].values())
    buckets = list(facts["buckets"].values())
    task_ids = {e["task_id"] for e in events if e["task_id"]}
    completed = {v["task_id"] for v in facts["task_states"].values() if v["state"] == "completed"}
    known = {e["entry_id"] for e in events if e["time"]["duration_type"] != "unknown"}
    exact = sum(b["seconds"] for b in buckets if b["duration_type"] == "exact")
    estimated = sum(b["seconds"] for b in buckets if b["duration_type"] == "estimated")
    project_seconds = defaultdict(int)
    technology_seconds = defaultdict(int)
    for b in buckets:
        project_seconds[b["project_id"]] += b["seconds"]
        for tech in b["technologies"]:
            technology_seconds[tech] += b["seconds"]
    count = len(events)
    return {"work_events": count, "completed_events": sum(e["status"] == "completed" for e in events), "identified_completed_tasks": len(completed), "identified_tasks": len(task_ids), "task_identity_coverage": (len([e for e in events if e["task_id"]]) / count if count else None), "active_projects": len({e["project_id"] for e in events}), "active_agents": len({e["agent_id"] for e in events}), "topics": len({e["topic_id"] or f"unassigned:{e['entry_id']}" for e in events}), "exact_seconds": exact, "estimated_seconds": estimated, "unknown_duration_events": sum(e["time"]["duration_type"] == "unknown" for e in events), "time_record_coverage": (len(known) / count if count else None), "project_seconds": dict(sorted(project_seconds.items())), "technology_seconds_overlapping": dict(sorted(technology_seconds.items())), "unfinished_identified_tasks": sum(x["state"] in ("planned", "in_progress", "blocked") for x in facts["task_snapshot"].values()), "unresolved_task_states": sum(x["state"] == "unresolved" for x in facts["task_snapshot"].values())}


def task_snapshot(events: list[dict], cutoff: datetime) -> dict:
    by_task = defaultdict(list)
    for event in events:
        state = event["task_state_event"]
        if event["task_id"] and state is not None and timestamp(state["occurred_at"]) < cutoff:
            by_task[event["task_id"]].append((timestamp(state["occurred_at"]), state["state"], event["entry_id"], event["revision_id"]))
    result = {}
    for task_id, declarations in by_task.items():
        latest = max(item[0] for item in declarations)
        heads = [item for item in declarations if item[0] == latest]
        states = {item[1] for item in heads}
        result[task_id] = {"state": next(iter(states)) if len(states) == 1 else "unresolved", "occurred_at": latest.isoformat(), "source_entry_ids": sorted({item[2] for item in heads}), "source_revision_ids": sorted({item[3] for item in heads})}
    return dict(sorted(result.items()))


def source_sections(facts: dict) -> tuple[dict, dict]:
    events = list(facts["events"].values())
    sections = {"achievements": [], "learning": [], "problems": [], "decisions": [], "unfinished": [], "suggestions": []}
    provenance = {}
    for event in events:
        row = {"title": event["title"], "summary": event["summary"], "entry_id": event["entry_id"], "agent_id": event["agent_id"], "project_id": event["project_id"], "work_date": event["work_date"]}
        if event["status"] == "completed":
            sections["achievements"].append(row)
        elif event["status"] == "blocked":
            sections["problems"].append(row)
        else:
            sections["unfinished"].append(row)
        if event["category"] == "learning":
            sections["learning"].append(row)
        if event["category"] == "design" and event["outputs"]:
            sections["decisions"].append(row)
        provenance[event["entry_id"]] = {"revision_id": event["revision_id"], "source_refs": [r["ref"] or f"{r['namespace']}:{r['source_id']}" for r in event["source_refs"]]}
    for entry_id, state in facts["task_states"].items():
        provenance.setdefault(entry_id, {"revision_id": state["revision_id"], "source_refs": [state["source_ref"]]})
    for value in sections.values():
        value.sort(key=lambda r: (r["work_date"], r["entry_id"]))
    return sections, dict(sorted(provenance.items()))


def active_agents(policy: dict, day: date) -> list[dict]:
    return [a for a in policy["agents"] if date.fromisoformat(a["enabled_from"]) <= day and (not a.get("enabled_until") or day <= date.fromisoformat(a["enabled_until"]))]


def daily_coverage(root: Path, policy: dict, day: date, events: list[dict], conflicts: list[str]) -> dict:
    expected = [a["agent_id"] for a in active_agents(policy, day) if a["required"]]
    received = []
    for agent in active_agents(policy, day):
        folder = root / "coverage" / day.strftime("%Y/%m/%d") / agent["agent_id"]
        current_digest = closure_digest(events, agent["agent_id"], day.isoformat())
        for file in folder.glob("*.json"):
            closure = json.loads(file.read_text(encoding="utf-8"))
            validate_shape(closure, "closure")
            if closure["input_digest"] == current_digest:
                received.append(agent["agent_id"])
                break
    received = sorted(set(received))
    return {"expected": sorted(expected), "received": received, "missing": sorted(set(expected) - set(received)), "conflicts": conflicts}


def report(root: Path, kind: str, key: str, as_of: datetime, agent_id: str | None = None, _context: dict | None = None) -> dict:
    if _context is None:
        policy = load_policy(root)
        event_list, conflicts = effective(all_revisions(root))
        from .overrides import apply_overrides
        event_list = apply_overrides(root, event_list)
        _context = {"policy": policy, "events": event_list, "conflicts": conflicts, "memo": {}}
    cache_key = (kind, key, agent_id)
    if cache_key in _context["memo"]:
        return _context["memo"][cache_key]
    policy = _context["policy"]
    zone = policy["timezone"]
    start, end, _ = period(kind, key, zone)
    local_as_of = as_of.astimezone(ZoneInfo(zone))
    event_list, conflicts = _context["events"], _context["conflicts"]
    if kind == "agent_daily":
        if agent_id is None:
            raise WorklogError("AGENT_REQUIRED")
        facts = daily_facts(event_list, key, zone, agent_id)
        coverage = daily_coverage(root, policy, start, event_list, conflicts)
        coverage["expected"] = [agent_id]
        coverage["missing"] = [agent_id] if agent_id not in coverage["received"] else []
        coverage["received"] = [agent_id] if agent_id in coverage["received"] else []
    elif kind == "daily":
        children = []
        for agent in active_agents(policy, start):
            children.append(report(root, "agent_daily", key, as_of, agent["agent_id"], _context))
        facts = merge_facts(children)
        coverage = daily_coverage(root, policy, start, event_list, conflicts)
    else:
        children = []
        if kind in ("weekly", "monthly"):
            day = start
            while day < end:
                children.append(report(root, "daily", day.isoformat(), as_of, _context=_context))
                day += timedelta(days=1)
        elif kind == "quarterly":
            for month in range(start.month, start.month + 3):
                children.append(report(root, "monthly", f"{start.year}-{month:02d}", as_of, _context=_context))
        else:
            for quarter in range(1, 5):
                children.append(report(root, "quarterly", f"{start.year}-Q{quarter}", as_of, _context=_context))
        facts = merge_facts(children)
        coverage = {"expected": [c["report_key"] for c in children], "received": [c["report_key"] for c in children if c["completeness"] == "complete"], "missing": [c["report_key"] for c in children if c["completeness"] != "complete"], "conflicts": sorted(set().union(*(c["coverage"]["conflicts"] for c in children)))}
    cutoff = min(datetime.combine(end, time.min, ZoneInfo(zone)), local_as_of)
    facts["task_snapshot"] = task_snapshot(event_list, cutoff)
    sections, provenance = source_sections(facts)
    close_time = policy["schedule"]["close_time"]
    hour, minute = map(int, close_time.split(":"))
    closed = local_as_of >= datetime.combine(end, time(hour, minute), ZoneInfo(zone)) if kind in ("daily", "agent_daily") else local_as_of.date() >= end
    result = {"schema_version": "1.0", "report_key": f"{kind}:{key}" + (f":{agent_id}" if agent_id else ""), "kind": kind, "agent_id": agent_id, "period": {"key": key, "timezone": zone, "start": datetime.combine(start, time.min, ZoneInfo(zone)).isoformat(), "end": datetime.combine(end, time.min, ZoneInfo(zone)).isoformat()}, "coverage": coverage, "lifecycle": "closed" if closed else "provisional", "completeness": "complete" if not coverage["missing"] and not coverage["conflicts"] and closed else "incomplete", "facts": facts, "metrics": metrics(facts), "sections": sections, "provenance": provenance, "analysis": {"mode": "template", "status": "available"}}
    validate_shape(result, "report")
    _context["memo"][cache_key] = result
    return result


def render_markdown(value: dict) -> str:
    m = value["metrics"]
    lines = [f"# {value['report_key']}", "", f"状态：{value['lifecycle']} / {value['completeness']}", f"事件：{m['work_events']}；完成事件：{m['completed_events']}；已识别完成任务：{m['identified_completed_tasks']}", f"Agent 记录时长：exact {m['exact_seconds']} 秒，estimated {m['estimated_seconds']} 秒；未知 {m['unknown_duration_events']} 条", "", "## 工作事项", ""]
    for row in value["sections"]["achievements"] + value["sections"]["unfinished"] + value["sections"]["problems"]:
        lines.append(f"- {row['work_date']} {row['title']}（{row['agent_id']}，来源 {row['entry_id']}）")
    if value["coverage"]["missing"]:
        lines.extend(["", "缺失上报或下级依赖：" + ", ".join(value["coverage"]["missing"])])
    return "\n".join(lines) + "\n"


def write_if_changed(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return False
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)
    return True


def build(root: Path, kind: str, key: str, as_of: datetime, agent_id: str | None = None, dry_run: bool = False) -> dict:
    value = report(root, kind, key, as_of, agent_id)
    relative = report_path(kind, key, agent_id)
    path = root / relative
    md_path = path.with_suffix(".md")
    site_path = root / "site" / kind / key / (agent_id or "index") / "index.html"
    env = Environment(loader=FileSystemLoader(TEMPLATE_ROOT), autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html").render(report=value).encode("utf-8")
    md = render_markdown(value).encode("utf-8")
    data = canonical(value)
    policy_digest = digest(load_policy(root))
    fact_fingerprint = digest({"facts": value["facts"], "policy": policy_digest, "rule": "1.0"})
    template_digest = hashlib.sha256((TEMPLATE_ROOT / "report.html").read_bytes()).hexdigest()
    start, end, _ = period(kind, key, load_policy(root)["timezone"])
    event_ids = set(value["facts"]["events"]) | {b["entry_id"] for b in value["facts"]["buckets"].values()}
    inputs = {}
    for input_path in revision_files(root):
        # Include all revisions of contributing events; amended work dates can invalidate both periods.
        entry_id = input_path.parent.name
        if entry_id in event_ids:
            inputs[str(input_path.relative_to(root))] = hashlib.sha256(input_path.read_bytes()).hexdigest()
    day = start
    while day < end:
        folder = root / "coverage" / day.strftime("%Y/%m/%d")
        for input_path in folder.glob("*/*.json"):
            if agent_id is None or input_path.parent.name == agent_id:
                inputs[str(input_path.relative_to(root))] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        day += timedelta(days=1)
    policy_path = root / "policy/worklog.yaml"
    inputs[str(policy_path.relative_to(root))] = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    for override_path in sorted((root / "overrides").glob("*.json")):
        inputs[str(override_path.relative_to(root))] = hashlib.sha256(override_path.read_bytes()).hexdigest()
    if kind == "daily":
        dependencies = [f"agent_daily:{key}:{a['agent_id']}" for a in active_agents(load_policy(root), start)]
    elif kind in ("weekly", "monthly"):
        dependencies = []
        day = start
        while day < end:
            dependencies.append(f"daily:{day.isoformat()}")
            day += timedelta(days=1)
    elif kind == "quarterly":
        dependencies = [f"monthly:{start.year}-{month:02d}" for month in range(start.month, start.month + 3)]
    elif kind == "yearly":
        dependencies = [f"quarterly:{start.year}-Q{quarter}" for quarter in range(1, 5)]
    else:
        dependencies = []
    manifest = {"schema_version": "1.0", "report_key": value["report_key"], "inputs": dict(sorted(inputs.items())), "dependencies": dependencies, "policy_digest": policy_digest, "core_version": __version__, "rule_version": "1.0", "template_version": template_digest, "fact_fingerprint": fact_fingerprint, "render_fingerprint": digest({"facts": fact_fingerprint, "template": template_digest}), "outputs": {str(relative): hashlib.sha256(data).hexdigest(), str(md_path.relative_to(root)): hashlib.sha256(md).hexdigest(), str(site_path.relative_to(root)): hashlib.sha256(html).hexdigest()}}
    validate_shape(manifest, "manifest")
    manifest_path = root / "manifests" / (value["report_key"].replace(":", "_") + ".json")
    if dry_run:
        return {"report_key": value["report_key"], "completeness": value["completeness"], "would_write": [str(relative), str(md_path.relative_to(root)), str(site_path.relative_to(root)), str(manifest_path.relative_to(root))]}
    changed = [write_if_changed(p, content) for p, content in ((path, data), (md_path, md), (site_path, html), (manifest_path, canonical(manifest)))]
    return {"report_key": value["report_key"], "lifecycle": value["lifecycle"], "completeness": value["completeness"], "changed": any(changed), "path": str(relative), "site": str(site_path.relative_to(root))}

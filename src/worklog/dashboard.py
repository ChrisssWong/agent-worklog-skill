"""Offline, source-linked overview pages without runtime fetch or CDN."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .core import all_revisions, effective, load_policy
from .reports import TEMPLATE_ROOT, write_if_changed


def build_dashboard(root: Path, as_of: datetime, dry_run: bool = False) -> dict:
    policy = load_policy(root)
    events, conflicts = effective(all_revisions(root))
    groups = {"year": defaultdict(list), "project": defaultdict(list), "technology": defaultdict(list), "agent": defaultdict(list)}
    for event in events:
        groups["year"][event["work_date"][:4]].append(event)
        groups["project"][event["project_id"]].append(event)
        groups["agent"][event["agent_id"]].append(event)
        for tag in event["technologies"]:
            groups["technology"][tag].append(event)
    pages = [(Path("site/index.html"), "工作记录索引", events)]
    for kind, paths in (("year", "years"), ("project", "projects"), ("technology", "technologies"), ("agent", "agents")):
        for key, items in sorted(groups[kind].items()):
            safe_key = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if kind == "technology" else key
            pages.append((Path("site") / paths / safe_key / "index.html", f"{kind}: {key}", items))
    pages.append((Path("site/growth/index.html"), "工作记录显示的主题变化", events))
    env = Environment(loader=FileSystemLoader(TEMPLATE_ROOT), autoescape=select_autoescape(["html"]))
    template = env.get_template("dashboard.html")
    changed = 0
    for relative, title, items in pages:
        records = sorted(items, key=lambda e: (e["work_date"], e["entry_id"]))
        active_days = len({e["work_date"] for e in records})
        technologies = sorted({t for e in records for t in e["technologies"]})
        technology_links = [(t, hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]) for t in technologies]
        years = sorted({e["work_date"][:4] for e in records})
        projects = sorted({e["project_id"] for e in records})
        agents = sorted({e["agent_id"] for e in records})
        date_range = (records[0]["work_date"], records[-1]["work_date"]) if records else (None, None)
        data_cutoff = max((e["recorded_at"] for e in records), default="无数据")
        html = template.render(title=title, records=records, active_days=active_days, technologies=technologies, technology_links=technology_links, years=years, projects=projects, agents=agents, date_range=date_range, conflicts=conflicts, as_of=data_cutoff, root_prefix="../" * (len(relative.parts) - 2)).encode("utf-8")
        if not dry_run:
            changed += write_if_changed(root / relative, html)
    return {"pages": [str(p) for p, _, _ in pages], "changed": changed, "dry_run": dry_run}

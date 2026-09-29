"""Offline, source-linked overview pages without runtime fetch or CDN."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .core import all_revisions, effective, load_policy, site_style
from .reports import TEMPLATE_ROOT, html_bytes, write_if_changed


def build_dashboard(root: Path, as_of: datetime, dry_run: bool = False) -> dict:
    policy = load_policy(root)
    events, conflicts = effective(all_revisions(root))
    from .overrides import apply_overrides
    events = apply_overrides(root, events)
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
            label = {"year": f"{key} 年工作记录", "project": f"项目：{key}", "technology": f"技术：{key}", "agent": f"Agent：{key}"}[kind]
            pages.append((Path("site") / paths / safe_key / "index.html", label, items))
    pages.append((Path("site/growth/index.html"), "工作记录显示的主题变化", events))
    env = Environment(loader=FileSystemLoader(TEMPLATE_ROOT), autoescape=select_autoescape(["html"]))
    template = env.get_template("dashboard.html")
    changed = 0
    for relative, title, items in pages:
        records = sorted(items, key=lambda e: (e["work_date"], e["entry_id"]), reverse=True)
        active_days = len({e["work_date"] for e in records})
        technologies = sorted({t for e in records for t in e["technologies"]})
        technology_links = [(t, hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]) for t in technologies]
        years = sorted({e["work_date"][:4] for e in records})
        growth_rows = []
        for technology in technologies:
            related = [e for e in records if technology in e["technologies"]]
            growth_rows.append({"technology": technology, "first": min(e["work_date"] for e in related), "last": max(e["work_date"] for e in related), "active_days": len({e["work_date"] for e in related}), "events": len(related), "projects": len({e["project_id"] for e in related})})
        projects = sorted({e["project_id"] for e in records})
        agents = sorted({e["agent_id"] for e in records})
        date_range = (records[0]["work_date"], records[-1]["work_date"]) if records else (None, None)
        data_cutoff = max((e["recorded_at"] for e in records), default="无数据")
        page_kind = "overview" if relative == Path("site/index.html") else "growth" if relative == Path("site/growth/index.html") else "detail"
        html = html_bytes(template.render(title=title, style=site_style(policy), page_kind=page_kind, records=records, active_days=active_days, technologies=technologies, technology_links=technology_links, years=years, projects=projects, agents=agents, date_range=date_range, conflicts=conflicts, as_of=data_cutoff, root_prefix="../" * (len(relative.parts) - 2), growth_rows=growth_rows, is_growth=page_kind == "growth"))
        if not dry_run:
            changed += write_if_changed(root / relative, html)
    return {"pages": [str(p) for p, _, _ in pages], "changed": changed, "dry_run": dry_run}

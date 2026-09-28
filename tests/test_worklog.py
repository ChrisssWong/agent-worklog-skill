import copy
import json
import subprocess
from html.parser import HTMLParser
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from worklog.core import WorklogError, capture, close_day, effective, all_revisions
from worklog.reports import report, build
from worklog.git_sync import sync
from worklog.orchestrate import run_due

POLICY = """schema_version: '1.0'
timezone: Asia/Shanghai
aggregator_id: codex
agents:
  - {agent_id: chatgpt, required: true, enabled_from: '2026-09-28'}
  - {agent_id: codex, required: true, enabled_from: '2026-09-28'}
  - {agent_id: claude-code, required: true, enabled_from: '2026-09-28'}
privacy: {excluded_terms: []}
schedule: {provisional_time: '23:00', close_time: '00:15'}
"""


def event(agent="codex", day="2026-09-28", task="t1", topic="s1", status="completed", dtype="estimated", seconds=1800, source="one"):
    return {"schema_version": "1.0", "entry_id": str(uuid.uuid4()), "revision_id": str(uuid.uuid4()), "parent_revision_ids": [], "revision_kind": "create", "agent_id": agent, "producer_instance_id": "test", "source_namespace": agent, "idempotency_key": f"test-{source}-{agent}", "partition_date": day, "work_date": day, "timezone": "Asia/Shanghai", "recorded_at": f"{day}T12:00:00+08:00", "source_refs": [{"namespace": agent, "source_id": source, "ref": f"test:{source}"}], "model": None, "project_id": "p1", "task_id": task, "topic_id": topic, "category": "implementation", "subcategories": [], "technologies": ["python"], "tags": [], "title": "合成工作", "summary": "仅供测试", "actions": [], "status": status, "task_state_event": None, "outputs": [], "time": {"activity_window": None, "duration_seconds": seconds, "duration_type": dtype, "evidence_ref": "test:timer" if dtype == "exact" else "test:estimate" if dtype == "estimated" else None, "allocation_method": "work_date", "segments": []}, "milestone": False, "importance": "normal"}


class WorklogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "policy").mkdir()
        (self.root / "policy/worklog.yaml").write_text(POLICY, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_g01_metrics_and_retry(self):
        one = event(agent="chatgpt", source="e1", seconds=1800)
        two = event(agent="codex", source="e2", dtype="exact", seconds=3600)
        two["task_state_event"] = {"state": "completed", "occurred_at": "2026-09-28T12:00:00+08:00", "source_ref": "test:e2"}
        three = event(agent="claude-code", source="e3", dtype="unknown", seconds=None)
        four = event(agent="codex", source="e4", task=None, topic="s2", status="in_progress", seconds=1200)
        for item in [one, two, three, four]:
            self.assertTrue(capture(self.root, item)["persisted"])
        for _ in range(10):
            retry = copy.deepcopy(two)
            retry["entry_id"] = str(uuid.uuid4())
            retry["revision_id"] = str(uuid.uuid4())
            self.assertFalse(capture(self.root, retry)["changed"])
        for agent in ["chatgpt", "codex", "claude-code"]:
            close_day(self.root, agent, "2026-09-28", "test-scope")
        r = report(self.root, "daily", "2026-09-28", datetime.fromisoformat("2026-09-29T01:00:00+08:00"))
        m = r["metrics"]
        self.assertEqual((m["work_events"], m["completed_events"], m["identified_completed_tasks"], m["topics"]), (4, 3, 1, 2))
        self.assertEqual((m["exact_seconds"], m["estimated_seconds"], m["unknown_duration_events"]), (3600, 3000, 1))
        self.assertEqual((m["time_record_coverage"], m["task_identity_coverage"]), (0.75, 0.75))
        self.assertEqual(r["completeness"], "complete")
        first = build(self.root, "daily", "2026-09-28", datetime.fromisoformat("2026-09-29T01:00:00+08:00"))
        second = build(self.root, "daily", "2026-09-28", datetime.fromisoformat("2026-09-29T01:00:00+08:00"))
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])

    def test_revision_conflict_then_resolve(self):
        original = event(source="rev")
        capture(self.root, original)
        one = copy.deepcopy(original)
        one.update(revision_id=str(uuid.uuid4()), parent_revision_ids=[original["revision_id"]], revision_kind="amend", revision_reason="修正", summary="版本一")
        two = copy.deepcopy(one)
        two.update(revision_id=str(uuid.uuid4()), summary="版本二")
        capture(self.root, one)
        capture(self.root, two)
        _, conflicts = effective(all_revisions(self.root))
        self.assertEqual(conflicts, [original["entry_id"]])
        resolved = copy.deepcopy(two)
        resolved.update(revision_id=str(uuid.uuid4()), parent_revision_ids=[one["revision_id"], two["revision_id"]], revision_kind="resolve", revision_reason="人工裁决")
        capture(self.root, resolved)
        events, conflicts = effective(all_revisions(self.root))
        self.assertEqual(len(events), 1)
        self.assertEqual(conflicts, [])

    def test_schema_privacy_and_cross_month(self):
        bad = event()
        bad["time"]["duration_type"] = "unknown"
        with self.assertRaises(WorklogError):
            capture(self.root, bad)
        first = event(day="2026-09-30", source="sep", seconds=2400)
        second = event(day="2026-10-01", source="oct", seconds=3000)
        for item in [first, second]:
            capture(self.root, item)
        now = datetime.fromisoformat("2026-10-08T00:30:00+08:00")
        week = report(self.root, "weekly", "2026-W40", now)
        sep = report(self.root, "monthly", "2026-09", now)
        octo = report(self.root, "monthly", "2026-10", now)
        self.assertEqual((week["metrics"]["estimated_seconds"], sep["metrics"]["estimated_seconds"], octo["metrics"]["estimated_seconds"]), (5400, 2400, 3000))
        secret = event(source="secret")
        secret["summary"] = "password=abc123456789"
        capture(self.root, secret)
        self.assertNotIn("abc123456789", json.dumps(all_revisions(self.root)))

    def test_offline_git_sync_only_stages_worklog_paths(self):
        subprocess.run(["git", "-c", "init.templateDir=/dev/null", "init", "-b", "main", str(self.root)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "policy/worklog.yaml"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "initial"], check=True, stdout=subprocess.DEVNULL)
        capture(self.root, event(source="sync"))
        self.assertEqual(sync(self.root)["sync"], "pending")
        self.assertEqual(sync(self.root)["committed"], False)
        (self.root / "unrelated.txt").write_text("user edit")
        with self.assertRaises(WorklogError) as ctx:
            sync(self.root)
        self.assertEqual(ctx.exception.code, "UNRELATED_GIT_CHANGE")

    def test_remote_input_race_stops_stale_sync(self):
        subprocess.run(["git", "-c", "init.templateDir=/dev/null", "init", "-b", "main", str(self.root)], check=True, stdout=subprocess.DEVNULL)
        for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
            subprocess.run(["git", "-C", str(self.root), "config", key, value], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "policy/worklog.yaml"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "initial"], check=True, stdout=subprocess.DEVNULL)
        remote = Path(self.temp.name).parent / f"worklog-remote-{uuid.uuid4()}"
        other = Path(self.temp.name).parent / f"worklog-other-{uuid.uuid4()}"
        try:
            subprocess.run(["git", "-c", "init.templateDir=/dev/null", "init", "--bare", "-b", "main", str(remote)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin", str(remote)], check=True)
            subprocess.run(["git", "-C", str(self.root), "push", "origin", "main"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-c", "init.templateDir=/dev/null", "clone", str(remote), str(other)], check=True, stdout=subprocess.DEVNULL)
            for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
                subprocess.run(["git", "-C", str(other), "config", key, value], check=True)
            capture(self.root, event(source="clone-a"))
            capture(other, event(source="clone-b"))
            self.assertEqual(sync(self.root)["sync"], "pushed")
            self.assertEqual(sync(other)["reason"], "REMOTE_INPUT_CHANGED_REBUILD_REQUIRED")
        finally:
            import shutil
            shutil.rmtree(remote, ignore_errors=True)
            shutil.rmtree(other, ignore_errors=True)

    def test_run_due_publishes_complete_snapshot_and_escapes_html(self):
        item = event(source="html")
        item["title"] = "<script>alert(1)</script>"
        capture(self.root, item)
        close_day(self.root, "codex", "2026-09-28", "test-scope")
        when = datetime.fromisoformat("2026-09-29T00:20:00+08:00")
        result = run_due(self.root, when)
        self.assertEqual(result["due"], 1)
        entry = Path(result["published"]["entry"])
        self.assertTrue(entry.exists())
        html = entry.read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        again = run_due(self.root, when)
        self.assertEqual(again["changed"], 0)
        self.assertEqual(again["published"]["version"], result["published"]["version"])
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.hrefs = []
            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.hrefs.extend(value for key, value in attrs if key == "href")
        for page in (self.root / "site/current").rglob("*.html"):
            parser = Links()
            parser.feed(page.read_text(encoding="utf-8"))
            for href in parser.hrefs:
                self.assertTrue((page.parent / href).resolve().exists(), f"broken link: {page}: {href}")

    def test_iso_year_and_measured_day_buckets(self):
        item = event(day="2027-01-01", source="newyear", dtype="exact", seconds=1200)
        item["time"]["allocation_method"] = "measured_segments"
        item["time"]["segments"] = [
            {"start": "2027-01-01T23:40:00+08:00", "end": "2027-01-02T00:00:00+08:00", "duration_seconds": 1200}
        ]
        capture(self.root, item)
        now = datetime.fromisoformat("2027-01-09T01:00:00+08:00")
        week = report(self.root, "weekly", "2026-W53", now)
        year = report(self.root, "yearly", "2027", now)
        self.assertEqual(week["metrics"]["work_events"], 1)
        self.assertEqual(week["metrics"]["exact_seconds"], 1200)
        self.assertEqual(year["metrics"]["work_events"], 1)
        self.assertEqual(year["metrics"]["exact_seconds"], 1200)

    def test_g03_amend_invalidates_closure_and_periods(self):
        original = event(day="2026-09-30", source="g03", seconds=2400)
        capture(self.root, original)
        close_day(self.root, "codex", "2026-09-30", "test-scope")
        later = event(day="2026-10-01", source="g03-oct", seconds=3000)
        capture(self.root, later)
        now = datetime.fromisoformat("2026-10-08T01:00:00+08:00")
        self.assertEqual(report(self.root, "weekly", "2026-W40", now)["metrics"]["estimated_seconds"], 5400)
        amended = copy.deepcopy(original)
        amended.update(revision_id=str(uuid.uuid4()), parent_revision_ids=[original["revision_id"]], revision_kind="amend", revision_reason="核对计时依据")
        amended["time"]["duration_seconds"] = 4200
        capture(self.root, amended)
        self.assertEqual(report(self.root, "weekly", "2026-W40", now)["metrics"]["estimated_seconds"], 7200)
        self.assertEqual(report(self.root, "monthly", "2026-09", now)["metrics"]["estimated_seconds"], 4200)
        self.assertEqual(report(self.root, "monthly", "2026-10", now)["metrics"]["estimated_seconds"], 3000)
        day = report(self.root, "daily", "2026-09-30", now)
        self.assertIn("codex", day["coverage"]["missing"])
        close_day(self.root, "codex", "2026-09-30", "test-scope")
        self.assertNotIn("codex", report(self.root, "daily", "2026-09-30", now)["coverage"]["missing"])

    def test_task_carry_over_rebuilds_future_periods(self):
        first = event(day="2026-09-28", source="state", status="completed")
        first["task_state_event"] = {"state": "completed", "occurred_at": "2026-09-28T12:00:00+08:00", "source_ref": "test:state"}
        capture(self.root, first)
        now = datetime.fromisoformat("2026-10-03T01:00:00+08:00")
        run_due(self.root, now)
        before = report(self.root, "daily", "2026-10-02", now)
        self.assertEqual(before["facts"]["task_snapshot"]["t1"]["state"], "completed")
        amended = copy.deepcopy(first)
        amended.update(revision_id=str(uuid.uuid4()), parent_revision_ids=[first["revision_id"]], revision_kind="amend", revision_reason="任务重新打开")
        amended["task_state_event"]["state"] = "in_progress"
        capture(self.root, amended)
        planned = run_due(self.root, now, dry_run=True)["due"]
        self.assertIn("daily:2026-10-02", planned)
        self.assertIn("monthly:2026-09", planned)
        run_due(self.root, now)
        after = report(self.root, "daily", "2026-10-02", now)
        self.assertEqual(after["facts"]["task_snapshot"]["t1"]["state"], "in_progress")
        self.assertEqual(after["metrics"]["unfinished_identified_tasks"], 1)

    def test_topic_override_groups_without_dropping_events(self):
        one = event(agent="chatgpt", source="topic-one", topic="initial")
        two = event(agent="codex", source="topic-two", topic="approved")
        capture(self.root, one)
        capture(self.root, two)
        (self.root / "overrides").mkdir()
        override = {"schema_version": "1.0", "override_id": str(uuid.uuid4()), "kind": "topic_alias", "targets": ["initial"], "value": "approved", "reason": "人工确认同主题", "source_ref": "test:review", "recorded_at": "2026-09-28T13:00:00+08:00"}
        (self.root / "overrides" / f"{override['override_id']}.json").write_text(json.dumps(override), encoding="utf-8")
        r = report(self.root, "daily", "2026-09-28", datetime.fromisoformat("2026-09-29T01:00:00+08:00"))
        self.assertEqual(r["metrics"]["work_events"], 2)
        self.assertEqual(r["metrics"]["topics"], 1)


if __name__ == "__main__":
    unittest.main()

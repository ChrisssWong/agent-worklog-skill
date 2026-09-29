"""Deterministic V1 capture, validation and immutable revision storage."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import yaml
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SECRET = re.compile(r"(?i)(?:bearer\s+[a-z0-9._~+/=-]{8,}|(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*[^\s,;]+|(?:sk|ghp|glpat)-[a-z0-9_-]{12,})")
SAFE_URL = {"https", "http"}


class WorklogError(Exception):
    def __init__(self, code: str, exit_code: int = 2):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate_shape(value: dict, name: str) -> None:
    errors = sorted(Draft202012Validator(schema(name), format_checker=FormatChecker()).iter_errors(value), key=lambda e: list(map(str, e.path)))
    if errors:
        path = ".".join(map(str, errors[0].path)) or "root"
        raise WorklogError(f"SCHEMA_INVALID:{name}:{path}")


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            raise ValueError
        return result
    except ValueError as exc:
        raise WorklogError("TIME_OFFSET_REQUIRED") from exc


def validate_event(event: dict, timezone: str) -> None:
    version = event.get("schema_version")
    validate_shape(event, "event-v1.0" if version == "1.0" else "event")
    try:
        ZoneInfo(timezone)
        ZoneInfo(event["timezone"])
        date.fromisoformat(event["work_date"])
        date.fromisoformat(event["partition_date"])
    except (ValueError, KeyError) as exc:
        raise WorklogError("DATE_OR_ZONE_INVALID") from exc
    timestamp(event["recorded_at"])
    kind = event["revision_kind"]
    parents = event["parent_revision_ids"]
    if (kind == "create") != (len(parents) == 0):
        raise WorklogError("REVISION_PARENT_INVALID")
    if kind != "create" and not event.get("revision_reason"):
        raise WorklogError("REVISION_REASON_REQUIRED")
    if kind in ("amend", "retract") and len(parents) != 1:
        raise WorklogError("REVISION_PARENT_INVALID")
    if kind == "resolve" and len(parents) < 2:
        raise WorklogError("RESOLVE_PARENTS_REQUIRED")
    if event["task_state_event"] is not None:
        if event["task_id"] is None:
            raise WorklogError("TASK_ID_REQUIRED")
        timestamp(event["task_state_event"]["occurred_at"])
    t = event["time"]
    duration = t["duration_seconds"]
    dtype = t["duration_type"]
    if (dtype is None or dtype == "unknown") != (duration is None):
        raise WorklogError("DURATION_TYPE_MISMATCH")
    if dtype is None and (t["evidence_ref"] is not None or t["segments"] or t["allocation_method"] != "work_date"):
        raise WorklogError("EMPTY_DURATION_INVALID")
    if dtype == "exact" and not t["evidence_ref"]:
        raise WorklogError("EXACT_EVIDENCE_REQUIRED")
    if dtype == "estimated" and not t["evidence_ref"]:
        raise WorklogError("ESTIMATE_BASIS_REQUIRED")
    window = t["activity_window"]
    if window is not None and timestamp(window["start"]) >= timestamp(window["end"]):
        raise WorklogError("ACTIVITY_WINDOW_INVALID")
    segments = t["segments"]
    if t["allocation_method"] == "measured_segments":
        if not segments or duration is None or sum(s["duration_seconds"] for s in segments) != duration:
            raise WorklogError("SEGMENT_SUM_INVALID")
        intervals = sorted((timestamp(s["start"]), timestamp(s["end"])) for s in segments)
        for i, (start, end) in enumerate(intervals):
            if start >= end or (i and start < intervals[i - 1][1]):
                raise WorklogError("SEGMENT_OVERLAP")
            if start.astimezone(ZoneInfo(timezone)).date() != (end - timedelta(microseconds=1)).astimezone(ZoneInfo(timezone)).date():
                raise WorklogError("SEGMENT_CROSSES_DAY")
    elif segments:
        raise WorklogError("SEGMENTS_NOT_ALLOWED")


def safe_text(value: object, excluded: list[str]) -> object:
    if isinstance(value, dict):
        return {k: safe_text(v, excluded) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_text(v, excluded) for v in value]
    if not isinstance(value, str):
        return value
    result = SECRET.sub("[REDACTED]", value)
    for term in excluded:
        result = result.replace(term, "[REDACTED]")
    # Do not persist credential-bearing or executable URLs.
    if "://" in result:
        parts = urlsplit(result) if result.startswith(("http://", "https://")) else None
        if parts is not None:
            if parts.username or parts.password or parts.query or parts.fragment:
                result = f"{parts.scheme}://{parts.hostname or ''}{parts.path}"
        elif re.search(r"(?i)\b(?:javascript|data|file):", result):
            raise WorklogError("UNSAFE_REFERENCE", 3)
    if re.search(r"(?i)\b(?:javascript|data|file):", result):
        raise WorklogError("UNSAFE_REFERENCE", 3)
    return result


def load_policy(root: Path) -> dict:
    path = root / "policy/worklog.yaml"
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        pairs = loader.construct_pairs(node)
        result = {}
        for key, value in pairs:
            if key in result:
                raise WorklogError("CONFIG_DUPLICATE_KEY")
            result[key] = value
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        policy = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
        # YAML converts unquoted dates into date objects; normalize before schema validation.
        for agent in policy["agents"]:
            for key in ("enabled_from", "enabled_until"):
                if isinstance(agent.get(key), date):
                    agent[key] = agent[key].isoformat()
        validate_shape(policy, "config")
        ZoneInfo(policy["timezone"])
        return policy
    except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as exc:
        raise WorklogError("CONFIG_INVALID") from exc


def site_style(policy: dict) -> str:
    """Return the configured site style; legacy policies default to the ledger."""
    return policy.get("site", {}).get("style", "ledger")


def confined(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise WorklogError("PATH_REJECTED", 3)
    root = root.resolve()
    target = root / relative
    for parent in [target, *target.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise WorklogError("SYMLINK_REJECTED", 3)
    if not target.resolve().is_relative_to(root):
        raise WorklogError("PATH_REJECTED", 3)
    return target


def atomic_json(path: Path, value: dict) -> bool:
    payload = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return False
        raise WorklogError("IMMUTABLE_PATH_CONFLICT", 6)
    fd, temp = tempfile.mkstemp(prefix=".worklog-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        # Link prevents overwriting a concurrent first writer.
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.read_bytes() == payload:
                return False
            raise WorklogError("IMMUTABLE_PATH_CONFLICT", 6)
        return True
    finally:
        Path(temp).unlink(missing_ok=True)


def revision_files(root: Path) -> list[Path]:
    return sorted((root / "raw").glob("*/*/*/*/*/*.json"))


def all_revisions(root: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in revision_files(root)]


def effective(revisions: list[dict]) -> tuple[list[dict], list[str]]:
    groups = defaultdict(dict)
    for item in revisions:
        validate_shape(item, "event-v1.0" if item.get("schema_version") == "1.0" else "event")
        key = item["entry_id"]
        rid = item["revision_id"]
        if rid in groups[key] and groups[key][rid] != item:
            raise WorklogError("REVISION_ID_COLLISION", 6)
        groups[key][rid] = item
    current, conflicts = [], []
    for entry_id, nodes in sorted(groups.items()):
        first = next(iter(nodes.values()))
        parents = set()
        if sum(rev["revision_kind"] == "create" for rev in nodes.values()) != 1:
            raise WorklogError("REVISION_GRAPH_INVALID", 6)
        for rev in nodes.values():
            if rev["agent_id"] != first["agent_id"] or rev["partition_date"] != first["partition_date"]:
                raise WorklogError("REVISION_IDENTITY_CONFLICT", 6)
            for parent in rev["parent_revision_ids"]:
                if parent not in nodes or parent == rev["revision_id"]:
                    raise WorklogError("REVISION_GRAPH_INVALID", 6)
                parents.add(parent)
        visited, visiting = set(), set()
        def visit(rid: str) -> None:
            if rid in visiting:
                raise WorklogError("REVISION_GRAPH_INVALID", 6)
            if rid in visited:
                return
            visiting.add(rid)
            for parent in nodes[rid]["parent_revision_ids"]:
                visit(parent)
            visiting.remove(rid)
            visited.add(rid)
        for rid in nodes:
            visit(rid)
        leaves = [rev for rid, rev in nodes.items() if rid not in parents]
        if len(leaves) != 1:
            conflicts.append(entry_id)
        elif leaves[0]["revision_kind"] != "retract":
            current.append(leaves[0])
    # Equivalent first writes from independent clones collapse under the stable retry token.
    by_token = defaultdict(list)
    for event in current:
        by_token[(event["agent_id"], event["source_namespace"], event["idempotency_key"])].append(event)
    deduped = []
    for items in by_token.values():
        payloads = {digest(event_payload(item)) for item in items}
        if len(payloads) > 1:
            conflicts.extend(item["entry_id"] for item in items)
        else:
            deduped.append(min(items, key=lambda e: e["entry_id"]))
    return sorted(deduped, key=lambda e: e["entry_id"]), sorted(set(conflicts))


def event_payload(event: dict) -> dict:
    ignore = {"entry_id", "revision_id", "parent_revision_ids", "revision_kind", "revision_reason", "recorded_at", "partition_date"}
    return {k: v for k, v in event.items() if k not in ignore}


def event_path(event: dict) -> Path:
    d = date.fromisoformat(event["partition_date"])
    return Path("raw") / d.strftime("%Y/%m/%d") / event["agent_id"] / event["entry_id"] / f"{event['revision_id']}.json"


def capture(root: Path, candidate: dict, dry_run: bool = False) -> dict:
    policy = load_policy(root)
    if not isinstance(candidate, dict):
        raise WorklogError("CANDIDATE_INVALID")
    if candidate.get("schema_version") != "1.1":
        raise WorklogError("EVENT_SCHEMA_VERSION_UNSUPPORTED")
    event = safe_text(candidate, policy["privacy"]["excluded_terms"])
    validate_event(event, policy["timezone"])
    if event["agent_id"] not in {a["agent_id"] for a in policy["agents"]}:
        raise WorklogError("AGENT_NOT_CONFIGURED", 3)
    previous = all_revisions(root)
    if event["revision_kind"] == "create":
        for item in previous:
            if (item["agent_id"], item["source_namespace"], item["idempotency_key"]) == (event["agent_id"], event["source_namespace"], event["idempotency_key"]):
                if digest(event_payload(item)) == digest(event_payload(event)):
                    return {"persisted": True, "changed": False, "entry_id": item["entry_id"], "revision_id": item["revision_id"], "sync": "offline"}
                raise WorklogError("IDEMPOTENCY_CONFLICT", 6)
    else:
        relevant = {v["revision_id"]: v for v in previous if v["entry_id"] == event["entry_id"]}
        if not relevant or not set(event["parent_revision_ids"]).issubset(relevant):
            raise WorklogError("REVISION_PARENT_MISSING", 6)
        first = next(iter(relevant.values()))
        if event["partition_date"] != first["partition_date"] or event["agent_id"] != first["agent_id"]:
            raise WorklogError("REVISION_IDENTITY_CONFLICT", 6)
    rel = event_path(event)
    path = confined(root, rel)
    if dry_run:
        return {"persisted": False, "would_write": str(rel), "entry_id": event["entry_id"], "revision_id": event["revision_id"]}
    changed = atomic_json(path, event)
    return {"persisted": True, "changed": changed, "entry_id": event["entry_id"], "revision_id": event["revision_id"], "sync": "offline"}


def closure_digest(events: list[dict], agent_id: str, work_date: str) -> str:
    ids = sorted(e["revision_id"] for e in events if e["agent_id"] == agent_id and e["work_date"] == work_date)
    return digest(ids)


def close_day(root: Path, agent_id: str, work_date: str, scope: str, dry_run: bool = False) -> dict:
    policy = load_policy(root)
    if not SLUG.fullmatch(agent_id) or agent_id not in {a["agent_id"] for a in policy["agents"]}:
        raise WorklogError("AGENT_NOT_CONFIGURED", 3)
    date.fromisoformat(work_date)
    events, conflicts = effective(all_revisions(root))
    if conflicts:
        raise WorklogError("REVISION_CONFLICT", 6)
    ids = sorted(e["revision_id"] for e in events if e["agent_id"] == agent_id and e["work_date"] == work_date)
    d = date.fromisoformat(work_date)
    folder = Path("coverage") / d.strftime("%Y/%m/%d") / agent_id
    old = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / folder).glob("*.json"))]
    input_digest = digest(ids)
    for item in old:
        if item["input_digest"] == input_digest and item["coverage_scope"] == scope:
            return {"persisted": True, "changed": False, "closure_id": item["closure_id"]}
    item = {"schema_version": "1.0", "closure_id": str(uuid.uuid4()), "agent_id": agent_id, "work_date": work_date, "coverage_scope": scope, "included_revision_ids": ids, "input_digest": input_digest, "declared_at": datetime.now().astimezone().isoformat(), "state": "reported" if ids else "no_activity", "supersedes_closure_ids": [x["closure_id"] for x in old]}
    validate_shape(item, "closure")
    rel = folder / f"{item['closure_id']}.json"
    if dry_run:
        return {"persisted": False, "would_write": str(rel), "state": item["state"]}
    atomic_json(confined(root, rel), item)
    return {"persisted": True, "changed": True, "closure_id": item["closure_id"], "state": item["state"]}

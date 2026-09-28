"""Apply explicit, versioned human mappings without changing raw revisions."""
from __future__ import annotations

import json
from pathlib import Path

from .core import SLUG, WorklogError, validate_shape


def apply_overrides(root: Path, events: list[dict]) -> list[dict]:
    overrides = []
    for path in sorted((root / "overrides").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        validate_shape(item, "override")
        overrides.append(item)
    mapping = {}
    excluded = set()
    for item in overrides:
        kind = item["kind"]
        if kind == "conflict_resolution":
            raise WorklogError("OVERRIDE_KIND_UNSUPPORTED", 2)
        if kind in ("topic_alias", "task_identity") and (not isinstance(item["value"], str) or not SLUG.fullmatch(item["value"])):
            raise WorklogError("OVERRIDE_VALUE_INVALID")
        if kind == "exclude" and item["value"] is not None:
            raise WorklogError("OVERRIDE_VALUE_INVALID")
        for target in item["targets"]:
            key = (kind, target)
            if key in mapping and mapping[key] != item["value"]:
                raise WorklogError("OVERRIDE_CONFLICT", 6)
            mapping[key] = item["value"]
            if kind == "exclude":
                excluded.add(target)
    result = []
    for event in events:
        if event["entry_id"] in excluded:
            continue
        copy = dict(event)
        topic = event["topic_id"]
        if topic is not None and ("topic_alias", topic) in mapping:
            copy["topic_id"] = mapping[("topic_alias", topic)]
        if ("task_identity", event["entry_id"]) in mapping:
            copy["task_id"] = mapping[("task_identity", event["entry_id"])]
        result.append(copy)
    return result

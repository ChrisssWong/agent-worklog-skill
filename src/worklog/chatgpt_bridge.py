"""Convert an explicit ChatGPT work declaration, not an entire conversation."""
from __future__ import annotations

import uuid
from datetime import date

from .core import WorklogError


def convert(document: dict) -> dict:
    if not isinstance(document, dict) or document.get("format") != "worklog-chatgpt-bridge-1" or document.get("agent_id") != "chatgpt":
        raise WorklogError("CHATGPT_BRIDGE_FORMAT_INVALID")
    allowed = {"format", "synthetic", "agent_id", "source_namespace", "conversation_id", "coverage_scope", "recorded_at", "timezone", "work"}
    if set(document) != allowed or not isinstance(document["synthetic"], bool):
        raise WorklogError("CHATGPT_BRIDGE_FIELDS_INVALID")
    item = document["work"]
    required = {"source_item_id", "work_date", "project_id", "task_id", "topic_id", "category", "title", "summary", "actions", "status", "task_state", "technologies", "outputs", "duration_type", "duration_seconds", "duration_basis"}
    if not isinstance(item, dict) or set(item) != required:
        raise WorklogError("CHATGPT_BRIDGE_WORK_INVALID")
    date.fromisoformat(item["work_date"])
    source_id = f"{document['conversation_id']}:{item['source_item_id']}"
    entry_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"agent-worklog/chatgpt/{source_id}"))
    revision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"agent-worklog/chatgpt/{source_id}/revision-1"))
    task_state_event = None
    if item["task_state"] is not None:
        task_state_event = {"state": item["task_state"], "occurred_at": document["recorded_at"], "source_ref": f"chatgpt:{source_id}"}
    return {
        "schema_version": "1.0", "entry_id": entry_id, "revision_id": revision_id,
        "parent_revision_ids": [], "revision_kind": "create", "agent_id": "chatgpt",
        "producer_instance_id": document["conversation_id"], "source_namespace": "chatgpt",
        "idempotency_key": f"chatgpt:{source_id}", "partition_date": item["work_date"],
        "work_date": item["work_date"], "timezone": document["timezone"],
        "recorded_at": document["recorded_at"],
        "source_refs": [{"namespace": "chatgpt", "source_id": source_id, "ref": None}],
        "model": None, "project_id": item["project_id"], "task_id": item["task_id"],
        "topic_id": item["topic_id"], "category": item["category"],
        "subcategories": [], "technologies": item["technologies"], "tags": ["synthetic"] if document["synthetic"] else [],
        "title": item["title"], "summary": item["summary"], "actions": item["actions"],
        "status": item["status"], "task_state_event": task_state_event, "outputs": item["outputs"],
        "time": {"activity_window": None, "duration_seconds": item["duration_seconds"],
                 "duration_type": item["duration_type"], "evidence_ref": item["duration_basis"],
                 "allocation_method": "work_date", "segments": []},
        "milestone": False, "importance": "normal"
    }

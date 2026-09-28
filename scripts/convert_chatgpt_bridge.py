#!/usr/bin/env python3
"""Convert a consented, structured ChatGPT bridge file into a candidate event."""
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "src"))

from worklog.chatgpt_bridge import convert  # noqa: E402
from worklog.core import canonical, validate_event  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: convert_chatgpt_bridge.py INPUT OUTPUT", file=sys.stderr)
        return 2
    source, target = map(Path, sys.argv[1:])
    document = json.loads(source.read_text(encoding="utf-8"))
    candidate = convert(document)
    validate_event(candidate, document["timezone"])
    target.write_bytes(canonical(candidate))
    print(json.dumps({"candidate": str(target), "entry_id": candidate["entry_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

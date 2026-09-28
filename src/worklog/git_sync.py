"""Bounded Git sync for a dedicated worklog clone."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .core import WorklogError

ALLOWED = ("raw/", "coverage/", "reports/", "manifests/", "metrics/", "site/", "analysis/", "overrides/", "policy/")


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise WorklogError("GIT_OPERATION_FAILED", 6)
    return result


def changed_paths(root: Path) -> list[str]:
    paths = set()
    for args in (("diff", "--name-only", "-z"), ("diff", "--name-only", "--cached", "-z"), ("ls-files", "--others", "--exclude-standard", "-z")):
        paths.update(x.decode("utf-8") for x in git(root, *args).stdout.split(b"\0") if x)
    return sorted(paths)


def sync(root: Path, remote: str = "origin", branch: str = "main", dry_run: bool = False, allowed_prefixes: tuple[str, ...] = ALLOWED) -> dict:
    root = root.resolve()
    top = Path(git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()).resolve()
    if top != root:
        raise WorklogError("DEDICATED_CLONE_REQUIRED", 3)
    paths = changed_paths(root)
    if any(not path.startswith(allowed_prefixes) or path.startswith("site/versions/") for path in paths):
        raise WorklogError("UNRELATED_GIT_CHANGE", 3)
    if git(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise WorklogError("STAGED_CHANGE_PRESENT", 3)
    if dry_run:
        return {"would_stage": paths, "sync": "dry_run"}
    if paths:
        git(root, "add", "--", *paths)
        git(root, "commit", "-m", "worklog: update validated records and reports")
    remotes = git(root, "remote").stdout.decode().split()
    if remote not in remotes:
        return {"committed": bool(paths), "sync": "pending", "reason": "REMOTE_NOT_CONFIGURED"}
    for attempt in range(3):
        fetched = git(root, "fetch", remote, branch, check=False)
        if fetched.returncode:
            return {"committed": bool(paths), "sync": "pending", "reason": "FETCH_FAILED"}
        local = git(root, "rev-parse", "HEAD").stdout.strip()
        upstream = git(root, "rev-parse", "FETCH_HEAD").stdout.strip()
        if local != upstream:
            base = git(root, "merge-base", "HEAD", "FETCH_HEAD").stdout.strip()
            if base != upstream:
                # A new remote input may invalidate derived reports. Stop for a fresh build.
                changed = git(root, "diff", "--name-only", base.decode(), "FETCH_HEAD").stdout.decode().splitlines()
                if any(path.startswith(("raw/", "coverage/", "policy/", "overrides/")) for path in changed):
                    return {"committed": bool(paths), "sync": "conflict", "reason": "REMOTE_INPUT_CHANGED_REBUILD_REQUIRED"}
                rebased = git(root, "rebase", "FETCH_HEAD", check=False)
                if rebased.returncode:
                    git(root, "rebase", "--abort", check=False)
                    return {"committed": bool(paths), "sync": "conflict", "reason": "REBASE_CONFLICT"}
        pushed = git(root, "push", remote, f"HEAD:{branch}", check=False)
        if pushed.returncode == 0:
            return {"committed": bool(paths), "sync": "pushed", "commit": git(root, "rev-parse", "HEAD").stdout.decode().strip()}
        time.sleep(0.2 * (attempt + 1))
    return {"committed": bool(paths), "sync": "pending", "reason": "PUSH_REJECTED"}

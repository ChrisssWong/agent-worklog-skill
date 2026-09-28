"""Publish only complete site snapshots through an atomic local pointer."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path


def publish(root: Path) -> dict:
    site = root / "site"
    versions = site / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in site.rglob("*.html") if "versions" not in p.relative_to(site).parts and "current" not in p.relative_to(site).parts)
    h = hashlib.sha256()
    for path in files:
        h.update(str(path.relative_to(site)).encode("utf-8"))
        h.update(path.read_bytes())
    version = h.hexdigest()[:20]
    final = versions / version
    if not final.exists():
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=versions))
        try:
            for path in files:
                target = staging / path.relative_to(site)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            staging.rename(final)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    pointer = site / "current"
    temp_link = site / ".current-next"
    temp_link.unlink(missing_ok=True)
    os.symlink(Path("versions") / version, temp_link)
    os.replace(temp_link, pointer)
    return {"version": version, "entry": str(pointer / "index.html")}

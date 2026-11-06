"""sources.lock.json: every external input the pipeline reads, pinned by URL and sha256.

The cache (data/cache) is not committed; the lockfile is. A fetch with a lockfile present
re-downloads only what is missing and fails if a downloaded file's hash differs from the
pinned one, so an upstream change can never slip into a build unnoticed. Updating a pin is an
explicit act (`--update`), and the lockfile diff is the review record.
"""
from __future__ import annotations

import hashlib
import json
import os

LOCK_PATH = "sources.lock.json"
CACHE_DIR = "data/cache"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_lock(path: str = LOCK_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_lock(lock: dict, path: str = LOCK_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(lock, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)

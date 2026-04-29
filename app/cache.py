"""JSON-on-disk cache with per-entry TTL. Thread-safe for reads; atomic writes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import CACHE_DIR


class Cache:
    def __init__(self, cache_dir: Path | None = None):
        self.dir = cache_dir or CACHE_DIR
        self.dir.mkdir(exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{hashlib.md5(key.encode()).hexdigest()}.json"

    def get(self, key: str, ttl: timedelta) -> Any:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if datetime.now() - datetime.fromisoformat(data["saved_at"]) > ttl:
                return None
            return data["value"]
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        p = self._path(key)
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"saved_at": datetime.now().isoformat(), "value": value}, default=str),
                encoding="utf-8",
            )
            tmp.replace(p)
        except Exception:
            pass

    def clear(self) -> int:
        count = 0
        for f in self.dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
        return count

    def stats(self) -> dict:
        files = list(self.dir.glob("*.json"))
        if not files:
            return {"count": 0, "size_kb": 0, "oldest": None, "newest": None}
        mtimes = [f.stat().st_mtime for f in files]
        return {
            "count": len(files),
            "size_kb": round(sum(f.stat().st_size for f in files) / 1024, 1),
            "oldest": datetime.fromtimestamp(min(mtimes)).strftime("%Y-%m-%d %H:%M"),
            "newest": datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M"),
        }


# Module-level singleton
cache = Cache()

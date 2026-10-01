"""Tiny thread-safe JSON persistence (users + recommendation history)."""
import copy
import json
import threading
from pathlib import Path

import config

_lock = threading.RLock()


class JsonStore:
    def __init__(self, filename: str, default):
        self.filename = filename
        self.default = default

    @property
    def path(self) -> Path:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return config.DATA_DIR / self.filename

    def load(self):
        with _lock:
            if not self.path.exists():
                return copy.deepcopy(self.default)
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return copy.deepcopy(self.default)

    def save(self, data) -> None:
        with _lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


users_store = JsonStore("users.json", {})
history_store = JsonStore("history.json", {})

"""Structured JSON logger for the closed-loop orchestrator."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_write_lock = Lock()


class JsonLogger:
    """Emit structured JSON log records to stdout."""

    def __init__(self, name: str):
        self._name = name

    def _emit(self, level: str, event_type: str, **kwargs):
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event_type": event_type,
            "service": kwargs.pop("service", "system"),
            "action": kwargs.pop("action", event_type.lower()),
            "result": kwargs.pop(
                "result",
                "fail" if level == "ERROR" else "warning" if level == "WARNING" else "info",
            ),
            **kwargs,
        }
        line = json.dumps(record)
        print(line, flush=True)
        audit_path = os.environ.get("AUDIT_LOG_PATH")
        if audit_path:
            path = Path(audit_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with _write_lock:
                with path.open("a") as handle:
                    handle.write(line + "\n")

    def info(self, event_type: str, **kwargs):
        self._emit("INFO", event_type, **kwargs)

    def warning(self, event_type: str, **kwargs):
        self._emit("WARNING", event_type, **kwargs)

    def error(self, event_type: str, **kwargs):
        self._emit("ERROR", event_type, **kwargs)

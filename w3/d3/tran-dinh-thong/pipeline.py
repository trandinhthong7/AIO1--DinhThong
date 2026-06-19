#!/usr/bin/env python3
"""Minimal Docker-state AIOps pipeline for the outage reproduction."""

import argparse
import asyncio
import subprocess
import time
from contextlib import asynccontextmanager
from threading import Lock

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

SERVICES = {
    "billing": "d3-aws-billing",
    "index": "d3-aws-index",
    "placement": "d3-aws-placement",
}
alerts: list[dict] = []
states: dict[str, str] = {}
lock = Lock()
poll_task = None


def container_state(container: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "missing"


async def monitor() -> None:
    while True:
        now = int(time.time())
        with lock:
            for service, container in SERVICES.items():
                current = container_state(container)
                previous = states.get(service)
                states[service] = current
                if previous == "running" and current != "running":
                    alerts.append(
                        {
                            "name": "InstanceUnavailable",
                            "service": service,
                            "state": current,
                            "fire_ts": now,
                            "severity": "critical" if service in {"index", "placement"} else "warning",
                        }
                    )
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poll_task
    for service, container in SERVICES.items():
        states[service] = container_state(container)
    poll_task = asyncio.create_task(monitor())
    yield
    poll_task.cancel()


app = FastAPI(title="W3-D3 Reproduction Pipeline", lifespan=lifespan)


class RcaWindow(BaseModel):
    window_start: int
    window_end: int


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "services": states}


@app.get("/alerts")
def get_alerts(since: int = 0) -> list[dict]:
    with lock:
        return [item for item in alerts if item["fire_ts"] >= since]


@app.post("/rca")
def rca(window: RcaWindow) -> dict:
    with lock:
        relevant = [
            item
            for item in alerts
            if rca_window_contains(item["fire_ts"], window.window_start, window.window_end)
        ]
    ordered = sorted(relevant, key=lambda item: (item["fire_ts"], item["service"]))
    # This intentionally represents the observed pipeline limitation: without
    # change/audit events, service-state signals cannot prove an operator command
    # was the root cause. It picks the first affected service instead.
    root = ordered[0]["service"] if ordered else None
    return {
        "root_service": root,
        "confidence": 0.42 if root else 0.0,
        "pattern": "simultaneous_multi_service_down" if len(ordered) >= 2 else "single_service_down",
        "evidence": [
            f"{item['service']} changed to {item['state']} at {item['fire_ts']}"
            for item in ordered
        ],
        "known_limitation": "No operator-command audit signal is available.",
    }


def rca_window_contains(ts: int, start: int, end: int) -> bool:
    return start <= ts <= end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

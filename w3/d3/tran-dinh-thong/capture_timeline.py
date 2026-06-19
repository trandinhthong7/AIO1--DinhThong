#!/usr/bin/env python3
"""Capture Docker transitions and pipeline observations with UTC timestamps."""

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SERVICES = {
    "billing": "d3-aws-billing",
    "index": "d3-aws-index",
    "placement": "d3-aws-placement",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state(container: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "missing"


def add(events: list[dict], source: str, event: str, **detail) -> None:
    events.append({"ts": now_iso(), "source": source, "event": event, **detail})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=25)
    parser.add_argument("--inject-after", type=int, default=4)
    parser.add_argument("--recover-after", type=int, default=12)
    parser.add_argument("--out", default="timeline.json")
    parser.add_argument("--inject-script", default="reproduction/inject.sh")
    parser.add_argument("--recover-script", default="reproduction/recover.sh")
    args = parser.parse_args()

    events: list[dict] = []
    start_epoch = int(time.time())
    last = {name: state(container) for name, container in SERVICES.items()}
    add(events, "capture", "capture_started", start_epoch=start_epoch)
    for service, current in last.items():
        add(events, "docker", "baseline_state", service=service, state=current)

    injected = False
    recovered = False
    observed_alert_keys: set[tuple] = set()
    deadline = time.time() + args.duration
    while time.time() < deadline:
        elapsed = time.time() - start_epoch
        if not injected and elapsed >= args.inject_after:
            add(events, "operator", "inject_started", intended_target="billing")
            completed = subprocess.run(
                ["/bin/bash", args.inject_script],
                capture_output=True,
                text=True,
            )
            add(
                events,
                "operator",
                "inject_completed",
                returncode=completed.returncode,
                output=completed.stdout.strip(),
            )
            injected = True

        if injected and not recovered and elapsed >= args.recover_after:
            add(events, "response", "recovery_started")
            completed = subprocess.run(
                ["/bin/bash", args.recover_script],
                capture_output=True,
                text=True,
            )
            add(
                events,
                "response",
                "recovery_completed",
                returncode=completed.returncode,
                output=completed.stdout.strip(),
            )
            recovered = True

        for service, container in SERVICES.items():
            current = state(container)
            if current != last[service]:
                add(
                    events,
                    "docker",
                    "container_state_changed",
                    service=service,
                    previous=last[service],
                    current=current,
                )
                last[service] = current

        try:
            response = requests.get(
                "http://localhost:8000/alerts",
                params={"since": start_epoch},
                timeout=2,
            )
            for alert in response.json():
                key = (alert["name"], alert["service"], alert["fire_ts"])
                if key not in observed_alert_keys:
                    observed_alert_keys.add(key)
                    add(events, "pipeline", "alert_observed", alert=alert)
        except Exception:
            pass
        time.sleep(1)

    add(events, "capture", "capture_completed", event_count_before_close=len(events))
    Path(args.out).write_text(json.dumps(events, indent=2))
    print(f"Wrote {args.out} with {len(events)} events")


if __name__ == "__main__":
    main()

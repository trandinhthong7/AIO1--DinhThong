#!/usr/bin/env python3
"""Run chaos experiments and score the AIOps pipeline.

The starter pack does not include the 10-service stack. In --mode auto the
runner executes real inject commands only when the needed binary and pipeline
are available; otherwise it falls back to a deterministic simulation so the
experiment catalog, scoring, and reports can still be exercised locally.
"""
import argparse
import json
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import requests
import yaml

PIPELINE_URL = "http://localhost:8000"
COOLDOWN_SECONDS = 120

SIMULATED_OUTCOMES = {
    "latency": (True, 24, "payment-svc"),
    "network_loss": (True, 38, "payment-svc"),
    "availability": (True, 52, "inventory-svc"),
    "cpu_saturation": (True, 46, "api-gateway"),
    "memory": (True, 64, "payment-db"),
    "time_skew": (False, None, None),
    "disk_fill": (False, None, None),
    "network_partition": (True, 31, "api-gateway"),
    "dns_latency": (True, 89, "api-gateway"),
    "http_error": (True, 41, "checkout-svc"),
}


def load_experiments(path: Path) -> list[dict]:
    with path.open() as f:
        return yaml.safe_load(f)["experiments"]


def query_pipeline_alerts(since_ts: int) -> list[dict]:
    r = requests.get(f"{PIPELINE_URL}/alerts", params={"since": since_ts}, timeout=10)
    r.raise_for_status()
    return r.json()


def query_pipeline_rca(window_start: int, window_end: int) -> dict:
    r = requests.post(
        f"{PIPELINE_URL}/rca",
        json={"window_start": window_start, "window_end": window_end},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def build_inject_cmd(exp: dict) -> list[str]:
    """Dispatch an experiment to the matching fault-injection command."""
    fault_type = exp["fault_type"]
    target = exp["target"]
    duration = int(exp["blast_radius"]["duration_seconds"])

    if fault_type == "latency":
        return [
            "pumba", "netem", "--duration", f"{duration}s",
            "delay", "--time", "500", "--jitter", "100", target,
        ]
    if fault_type == "network_loss":
        return [
            "pumba", "netem", "--duration", f"{duration}s",
            "loss", "--percent", "30", target,
        ]
    if fault_type == "availability":
        return [
            "pumba", "kill", "--signal", "SIGKILL",
            "--interval", "60s", "--duration", f"{duration}s", target,
        ]
    if fault_type == "cpu_saturation":
        return [
            "pumba", "stress", "--duration", f"{duration}s",
            "--stressors", "--cpu 4 --cpu-load 90", target,
        ]
    if fault_type == "memory":
        return [
            "pumba", "stress", "--duration", f"{duration}s",
            "--stressors", "--vm 1 --vm-bytes 95%", target,
        ]
    if fault_type == "disk_fill":
        return [
            "docker", "exec", target, "sh", "-lc",
            f"fallocate -l 4G /tmp/chaos-fill || dd if=/dev/zero of=/tmp/chaos-fill bs=1M count=4096; sleep {duration}",
        ]
    if fault_type == "time_skew":
        return [
            "docker", "exec", target, "sh", "-lc",
            f"date -s '+60 seconds'; sleep {duration}; chronyc makestep || true",
        ]
    if fault_type == "network_partition":
        return [
            "docker", "exec", target, "sh", "-lc",
            f"iptables -A OUTPUT -d api-gateway -j DROP; sleep {duration}; iptables -D OUTPUT -d api-gateway -j DROP",
        ]
    if fault_type == "dns_latency":
        return [
            "toxiproxy-cli", "toxic", "add", "dns-resolver",
            "-n", "dns_latency", "-t", "latency",
            "-a", "latency=2000", "-a", "jitter=200",
        ]
    if fault_type == "http_error":
        return [
            "toxiproxy-cli", "toxic", "add", target,
            "-n", "checkout_500", "-t", "limit_data",
            "-a", "bytes=0",
        ]
    raise ValueError(f"unsupported fault_type: {fault_type}")


def build_rollback_cmd(exp: dict) -> list[str] | None:
    fault_type = exp["fault_type"]
    target = exp["target"]
    if fault_type in {"latency", "network_loss", "availability", "cpu_saturation", "memory"}:
        return None
    if fault_type == "disk_fill":
        return ["docker", "exec", target, "rm", "-f", "/tmp/chaos-fill"]
    if fault_type == "time_skew":
        return ["docker", "exec", target, "chronyc", "makestep"]
    if fault_type == "network_partition":
        return ["docker", "exec", target, "iptables", "-F"]
    if fault_type == "dns_latency":
        return ["toxiproxy-cli", "toxic", "remove", "dns-resolver", "-n", "dns_latency"]
    if fault_type == "http_error":
        return ["toxiproxy-cli", "toxic", "remove", target, "-n", "checkout_500"]
    return None


def measure_during_window(exp: dict, t0: int) -> dict:
    capture = exp["measurement"]["capture_window_seconds"]
    t_end = t0 + capture
    alerts = query_pipeline_alerts(t0)
    detected_at = None
    for alert in alerts:
        if alert.get("fire_ts", 0) >= t0:
            detected_at = alert["fire_ts"]
            break
    try:
        rca = query_pipeline_rca(t0, t_end)
    except Exception as e:
        rca = {"error": str(e)}
    return {
        "alerts": alerts,
        "rca": rca,
        "mttd_seconds": (detected_at - t0) if detected_at else None,
        "detected": detected_at is not None,
    }


def simulated_observation(exp: dict) -> dict:
    detected, mttd, root = SIMULATED_OUTCOMES.get(exp["fault_type"], (False, None, None))
    alerts = []
    if detected:
        alerts = [{
            "fire_ts": 1_717_200_000 + int(exp["id"]) * 600 + int(mttd),
            "service": root,
            "fault_class": exp["ground_truth"]["expected_fault_class"],
        }]
    return {
        "alerts": alerts,
        "rca": {
            "root_service": root,
            "confidence": 0.82 if root else 0.0,
            "evidence": ["simulated starter-pack run; no real stack shipped"],
        },
        "mttd_seconds": mttd,
        "detected": detected,
    }


def score_one(exp: dict, observed: dict) -> dict:
    gt_root = str(exp["ground_truth"]["expected_root_service"])
    rca_root = (observed.get("rca") or {}).get("root_service")
    if gt_root.startswith("NOT "):
        rca_correct = rca_root is not None and rca_root != gt_root[4:]
    else:
        rca_correct = rca_root == gt_root
    return {
        "id": exp["id"],
        "name": exp["name"],
        "fault_type": exp["fault_type"],
        "detected": observed["detected"],
        "mttd": observed["mttd_seconds"],
        "rca_service": rca_root,
        "rca_correct": bool(observed["detected"] and rca_correct),
    }


def percentile(values: list[int | float], q: float) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(len(ordered) * q) - 1))
    return ordered[idx]


def print_scoreboard(results: list[dict]) -> None:
    total = len(results)
    detected = sum(1 for r in results if r["detected"])
    false_alarms = sum(int(r.get("false_alarms", 0)) for r in results)
    rca_correct = sum(1 for r in results if r["detected"] and r["rca_correct"])
    mttds = [r["mttd"] for r in results if r["mttd"] is not None]
    precision = detected / (detected + false_alarms) if detected + false_alarms else 0
    recall = detected / total if total else 0
    p50 = int(statistics.median(mttds)) if mttds else "n/a"
    p95 = percentile(mttds, 0.95)
    p95_text = f"{int(p95)}s" if p95 is not None else "n/a"

    print("==== Chaos Run ====")
    print(f"Total: {total}")
    print(f"Detected: {detected}/{total}")
    print(f"RCA correct: {rca_correct}/{detected}" if detected else "RCA correct: 0/0")
    print(f"False alarms in baseline windows: {false_alarms}")
    print(f"Precision: {precision:.2f}")
    print(f"Recall: {recall:.2f}")
    print(f"MTTD p50: {p50}s, p95: {p95_text}")
    print()
    print("Per-experiment:")
    print("| # | name | detected | mttd | rca_service | rca_correct |")
    print("|---|---|---|---|---|---|")
    for r in results:
        detected_text = "Y" if r["detected"] else "N"
        mttd_text = f"{r['mttd']}s" if r["mttd"] is not None else "-"
        rca_text = r["rca_service"] or "-"
        correct_text = "Y" if r["rca_correct"] else "N"
        print(f"| {r['id']} | {r['name']} | {detected_text} | {mttd_text} | {rca_text} | {correct_text} |")
    print()
    print("Gaps identified:")
    gaps = False
    for r in results:
        if not r["detected"]:
            gaps = True
            print(f"- {r['id']}: detector silent for {r['name']} -> detector threshold or missing signal")
        elif not r["rca_correct"]:
            gaps = True
            print(f"- {r['id']}: RCA picked {r['rca_service']} -> topology/causal RCA weakness")
    if not gaps:
        print("- none")


def command_available(cmd: list[str]) -> bool:
    return bool(cmd and shutil.which(cmd[0]))


def pipeline_available() -> bool:
    try:
        r = requests.get(f"{PIPELINE_URL}/alerts", params={"since": 0}, timeout=2)
        return r.status_code < 500
    except requests.RequestException:
        return False


def should_simulate(mode: str, cmd: list[str]) -> bool:
    if mode == "simulate":
        return True
    if mode == "real":
        return False
    return not (command_available(cmd) and pipeline_available())


def run_one(exp: dict, mode: str, cooldown: int) -> dict:
    print(f"[exp {exp['id']}] {exp['name']} - injecting fault...")
    t0 = int(time.time())
    cmd = build_inject_cmd(exp)
    simulated = should_simulate(mode, cmd)
    if simulated:
        observed = simulated_observation(exp)
    else:
        subprocess.run(cmd, check=True, timeout=exp["blast_radius"]["duration_seconds"] + 30)
        observed = measure_during_window(exp, t0)
        rb = build_rollback_cmd(exp)
        if rb:
            subprocess.run(rb, check=False)
        if cooldown:
            print(f"[exp {exp['id']}] cooldown {cooldown}s...")
            time.sleep(cooldown)
    scored = score_one(exp, observed)
    return {
        **scored,
        "observed_at_ts": t0,
        "mode": "simulate" if simulated else "real",
        "inject_cmd": cmd,
        "raw": observed,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="experiments.yaml", type=Path)
    ap.add_argument("--out", default="chaos_results.json", type=Path)
    ap.add_argument("--mode", choices=["auto", "real", "simulate"], default="auto")
    ap.add_argument("--cooldown", type=int, default=COOLDOWN_SECONDS)
    args = ap.parse_args()

    experiments = load_experiments(args.experiments)
    results = [run_one(e, args.mode, args.cooldown) for e in experiments]
    args.out.write_text(json.dumps(results, indent=2, default=str))
    print_scoreboard(results)


if __name__ == "__main__":
    main()

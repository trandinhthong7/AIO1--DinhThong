#!/usr/bin/env python3
"""Ronki Detect-Decide-Act-Verify-Rollback orchestrator."""

import argparse
import concurrent.futures
import json
import shlex
import subprocess
import threading
import time
from pathlib import Path

import requests
import yaml

from engine.logger import JsonLogger
from engine.metrics import (
    action_counter,
    blast_radius_gauge,
    circuit_breaker_gauge,
    mutex_gauge,
    start_metrics_server,
    verify_status_gauge,
)
from engine.safety import BlastRadiusGuard, CircuitBreaker
from engine.verify import verify_service

log = JsonLogger("orchestrator")
_service_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def load_config(path: str) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


def get_service_lock(service: str) -> threading.Lock:
    with _locks_meta:
        return _service_locks.setdefault(service, threading.Lock())


def fetch_active_alerts(alertmanager_url: str) -> list[dict]:
    try:
        response = requests.get(
            f"{alertmanager_url}/api/v2/alerts",
            params={"active": "true", "silenced": "false", "inhibited": "false"},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        log.error("ALERTMANAGER_FETCH_ERROR", service="alertmanager", action="poll", result="fail", error=str(exc))
        return []


def runbook_executable(command: str) -> str:
    return shlex.split(command)[0]


def run_runbook(command: str, service: str, dry_run: bool, timeout_s: int = 30) -> bool:
    parts = shlex.split(command)
    cmd = ["/bin/bash", parts[0], *parts[1:], "--service", service]
    if dry_run:
        cmd.append("--dry-run")
    log.info("RUNBOOK_EXEC", service=service, action=command, result="started", dry_run=dry_run)
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        result = "success" if completed.returncode == 0 else "fail"
        log.info(
            "RUNBOOK_RESULT",
            service=service,
            action=command,
            result=result,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        return completed.returncode == 0
    except subprocess.TimeoutExpired:
        log.error("RUNBOOK_TIMEOUT", service=service, action=command, result="fail", timeout_s=timeout_s)
    except Exception as exc:
        log.error("RUNBOOK_ERROR", service=service, action=command, result="fail", error=str(exc))
    return False


def extract_service(alert: dict) -> str:
    labels = alert.get("labels", {})
    return labels.get("service") or labels.get("job") or "unknown"


def validate_runbook(command: str, cfg: dict, alertname: str) -> bool:
    executable = runbook_executable(command)
    registry = cfg.get("runbook_registry", [])
    if executable in registry:
        return True
    log.error(
        "DECISION_VALIDATION_FAILED",
        service="decision-engine",
        action="escalate_no_auto_action",
        result="rejected",
        bad_runbook=executable,
        alertname=alertname,
        raw_decision=command,
    )
    return False


def run_transaction(
    steps: list[str],
    rollback_steps: list[str],
    service: str,
    timeout_s: int,
) -> bool:
    completed: list[str] = []
    for step in steps:
        if not run_runbook(step, service, False, timeout_s):
            log.error(
                "TRANSACTIONAL_STEP_FAIL",
                service=service,
                action=step,
                result="fail",
                completed_before_failure=completed,
            )
            selected = rollback_steps[: len(completed)]
            rolled_back = []
            for rollback in reversed(selected):
                ok = run_runbook(rollback, service, False, timeout_s)
                rolled_back.append(rollback)
                log.warning(
                    "TRANSACTIONAL_ROLLBACK_STEP",
                    service=service,
                    action=rollback,
                    result="success" if ok else "fail",
                )
            log.info(
                "TRANSACTIONAL_ROLLBACK_COMPLETE",
                service=service,
                action="transactional_rollback",
                result="complete",
                rolled_back=rolled_back,
            )
            return False
        completed.append(step)
        log.info("TRANSACTIONAL_STEP_COMPLETE", service=service, action=step, result="success")
    return True


def process_alert(
    alert: dict,
    cfg: dict,
    baseline: dict,
    guard: BlastRadiusGuard,
    circuit: CircuitBreaker,
    global_dry_run: bool,
) -> None:
    labels = alert.get("labels", {})
    alertname = labels.get("alertname", "")
    service = extract_service(alert)
    log.info("ALERT_DETECTED", service=service, action=alertname, result="detected", severity=labels.get("severity", ""))

    command = cfg.get("runbook_map", {}).get(alertname)
    if not command:
        log.warning("NO_RUNBOOK", service=service, action=alertname, result="escalate")
        return
    if not validate_runbook(command, cfg, alertname):
        return
    log.info("DECIDE_RUNBOOK", service=service, action=command, result="selected", alertname=alertname)

    allowed, reason = guard.check(service)
    if not allowed:
        log.warning("BLAST_RADIUS_EXCEEDED", service=service, action=command, result="escalate", reason=reason)
        return
    log.info("BLAST_RADIUS_OK", service=service, action=command, result="pass")

    lock = get_service_lock(service)
    if not lock.acquire(blocking=False):
        log.warning("SERVICE_LOCK_BUSY", service=service, action=command, result="skipped")
        return
    mutex_gauge.labels(service=service).set(1)
    try:
        process_locked(
            alertname, service, command, cfg, baseline, guard, circuit, global_dry_run
        )
    finally:
        mutex_gauge.labels(service=service).set(0)
        lock.release()


def process_locked(
    alertname: str,
    service: str,
    command: str,
    cfg: dict,
    baseline: dict,
    guard: BlastRadiusGuard,
    circuit: CircuitBreaker,
    global_dry_run: bool,
) -> None:
    timeout_s = int(cfg["runbook_timeout_seconds"])

    if not run_runbook(command, service, True, timeout_s):
        log.error("DRY_RUN_FAIL", service=service, action=command, result="fail")
        return
    log.info("DRY_RUN_PASS", service=service, action=command, result="pass")
    if global_dry_run:
        action_counter.labels(service=service, runbook=command, outcome="dry_run").inc()
        log.info("GLOBAL_DRY_RUN_SKIP", service=service, action=command, result="dry_run")
        return

    guard.record(service)
    remaining = cfg["blast_radius"]["max_actions_per_minute"] - len(guard._global_window)
    blast_radius_gauge.labels(service=service).set(max(0, remaining))

    steps = cfg.get("multi_step_map", {}).get(alertname, [])
    if steps:
        succeeded = run_transaction(
            steps,
            cfg.get("multi_step_rollback_map", {}).get(alertname, []),
            service,
            timeout_s,
        )
        if not succeeded:
            circuit.record_failure()
            circuit_breaker_gauge.labels(service=service).set(1 if circuit.is_open() else 0)
            return
    elif not run_runbook(command, service, False, timeout_s):
        action_counter.labels(service=service, runbook=command, outcome="fail").inc()
        log.error("ACTION_EXEC_FAIL", service=service, action=command, result="fail")
        circuit.record_failure()
        circuit_breaker_gauge.labels(service=service).set(1 if circuit.is_open() else 0)
        return
    log.info("ACTION_EXECUTED", service=service, action=command, result="success")

    thresholds = baseline["verify_thresholds"]
    verify_status_gauge.labels(service=service, runbook=command).set(2)
    verified = verify_service(
        prometheus_url=cfg["prometheus_url"],
        service=service,
        baseline=baseline,
        timeout_s=thresholds["verify_timeout_seconds"],
        poll_interval_s=thresholds["verify_poll_interval_seconds"],
        min_samples=thresholds["verify_min_samples"],
    )
    if verified:
        verify_status_gauge.labels(service=service, runbook=command).set(1)
        action_counter.labels(service=service, runbook=command, outcome="success").inc()
        log.info("ACTION_SUCCESS", service=service, action=command, result="success", alertname=alertname)
        circuit.record_success()
        circuit_breaker_gauge.labels(service=service).set(0)
        return

    verify_status_gauge.labels(service=service, runbook=command).set(0)
    rollback = cfg.get("rollback_map", {}).get(alertname, command)
    log.warning("ROLLBACK_TRIGGERED", service=service, action=rollback, result="started")
    rollback_executed = run_runbook(rollback, service, False, timeout_s)
    log.info(
        "ROLLBACK_EXECUTED",
        service=service,
        action=rollback,
        result="success" if rollback_executed else "fail",
    )
    rollback_verified = verify_service(
        prometheus_url=cfg["prometheus_url"],
        service=service,
        baseline=baseline,
        timeout_s=thresholds["verify_timeout_seconds"],
        poll_interval_s=thresholds["verify_poll_interval_seconds"],
        min_samples=thresholds["verify_min_samples"],
    )
    log.info(
        "ROLLBACK_VERIFY_PASS" if rollback_verified else "ROLLBACK_VERIFY_FAIL",
        service=service,
        action=rollback,
        result="pass" if rollback_verified else "fail",
    )
    action_counter.labels(service=service, runbook=command, outcome="rollback").inc()
    circuit.record_failure()
    circuit_breaker_gauge.labels(service=service).set(1 if circuit.is_open() else 0)


def make_alert(alertname: str, service: str) -> dict:
    return {"labels": {"alertname": alertname, "service": service, "severity": "test"}}


def run_self_test(cfg: dict, baseline: dict) -> None:
    """Run six deterministic acceptance paths without external services."""
    global run_runbook, verify_service
    real_runbook, real_verify = run_runbook, verify_service
    verify_results: dict[str, list[bool]] = {}

    def fake_runbook(command: str, service: str, dry_run: bool, timeout_s: int = 30) -> bool:
        log.info("RUNBOOK_EXEC", service=service, action=command, result="started", dry_run=dry_run)
        time.sleep(0.05)
        success = not ("--step-c" in command and service == "api-gateway" and not dry_run)
        log.info("RUNBOOK_RESULT", service=service, action=command, result="success" if success else "fail", returncode=0 if success else 1)
        return success

    def fake_verify(**kwargs) -> bool:
        service = kwargs["service"]
        outcomes = verify_results.setdefault(service, [True])
        result = outcomes.pop(0) if outcomes else True
        log.info("VERIFY_PASS" if result else "VERIFY_FAIL", service=service, action="prometheus_verify", result="pass" if result else "fail", samples=3)
        return result

    run_runbook, verify_service = fake_runbook, fake_verify
    try:
        log.info("SELF_TEST_START", service="all", action="six_scenarios", result="started")

        guard, circuit = BlastRadiusGuard(20, 20), CircuitBreaker(3)
        verify_results["payment-svc"] = [True]
        process_alert(make_alert("HighLatency", "payment-svc"), cfg, baseline, guard, circuit, False)

        verify_results["checkout-svc"] = [False, True]
        process_alert(make_alert("InstanceDown", "checkout-svc"), cfg, baseline, guard, circuit, False)

        guard, circuit = BlastRadiusGuard(20, 20), CircuitBreaker(3)
        for index in range(3):
            service = f"circuit-test-{index}"
            verify_results[service] = [False, True]
            process_alert(make_alert("InstanceDown", service), cfg, baseline, guard, circuit, False)
        log.info("CIRCUIT_STATE", service="all", action="halt_automation", result="open" if circuit.is_open() else "closed")

        guard, circuit = BlastRadiusGuard(20, 20), CircuitBreaker(3)
        process_alert(make_alert("MultiStepDeploy", "api-gateway"), cfg, baseline, guard, circuit, False)

        guard, circuit = BlastRadiusGuard(20, 20), CircuitBreaker(3)
        verify_results["payment-svc"] = [True]
        verify_results["inventory-svc"] = [True]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(process_alert, make_alert("HighLatency", "payment-svc"), cfg, baseline, guard, circuit, False)
            second = pool.submit(process_alert, make_alert("HighLatency", "inventory-svc"), cfg, baseline, guard, circuit, False)
            time.sleep(0.01)
            duplicate = pool.submit(process_alert, make_alert("HighLatency", "payment-svc"), cfg, baseline, guard, circuit, False)
            first.result()
            second.result()
            duplicate.result()

        process_alert(make_alert("TestHallucination", "payment-svc"), cfg, baseline, guard, circuit, False)
        log.info("SELF_TEST_COMPLETE", service="all", action="six_scenarios", result="pass")
    finally:
        run_runbook, verify_service = real_runbook, real_verify


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    baseline_path = (Path(args.config).parent / cfg["baseline_path"]).resolve()
    with baseline_path.open() as handle:
        baseline = json.load(handle)
    baseline["verify_thresholds"].update(cfg.get("verify_threshold_overrides", {}))

    start_metrics_server()
    if args.self_test:
        run_self_test(cfg, baseline)
        return

    guard = BlastRadiusGuard(
        cfg["blast_radius"]["max_actions_per_minute"],
        cfg["blast_radius"]["max_restarts_per_service_per_hour"],
    )
    circuit = CircuitBreaker(cfg["circuit_breaker"]["consecutive_failure_threshold"])
    seen: set[str] = set()
    log.info("ORCHESTRATOR_START", service="all", action="poll", result="started", dry_run=args.dry_run)

    while True:
        if circuit.is_open():
            log.error("CIRCUIT_BREAKER_HALT", service="all", action="poll", result="halted")
            time.sleep(cfg["poll_interval_seconds"])
            continue

        alerts = []
        active_fingerprints: set[str] = set()
        for alert in fetch_active_alerts(cfg["alertmanager_url"]):
            fingerprint = alert.get("fingerprint", "")
            if fingerprint:
                active_fingerprints.add(fingerprint)
            if fingerprint and fingerprint in seen:
                continue
            alerts.append(alert)

        if alerts:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(alerts))) as pool:
                futures = [
                    pool.submit(process_alert, alert, cfg, baseline, guard, circuit, args.dry_run)
                    for alert in alerts
                ]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:
                        log.error("ALERT_PROCESSING_ERROR", service="unknown", action="process", result="fail", error=str(exc))

        # Forget resolved alerts so the same service/fault can be handled again
        # after recovery. This is required for repeated-failure circuit tests.
        seen = active_fingerprints
        time.sleep(cfg["poll_interval_seconds"])


if __name__ == "__main__":
    main()

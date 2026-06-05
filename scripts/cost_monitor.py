"""GCP 비용 감축 후 모니터링 — sample 수집 + JSONL append.

수집 항목:
1. Cloud Run Service 설정 snapshot (revision, memory, cpu, min/max, concurrency, cpu-throttling)
2. HTTP health check (latency, status code)
3. 최근 1시간 에러 로그 카운트 (severity=ERROR, OOM/throttling 키워드 포함)
4. Cloud Run Job 실행 통계 (지난 24h execution count + 평균 duration)
5. 활성 instance 수 (Cloud Monitoring API 가능 시)
6. 메모리/CPU 사용량 평균 (Cloud Monitoring API 가능 시)

사용:
  python scripts/cost_monitor.py                 # 한 번 수집 → logs/cost_monitor.jsonl append
  python scripts/cost_monitor.py --print         # 수집 후 stdout 출력만 (저장 X)
  python scripts/cost_monitor.py --no-logs       # 에러 로그 수집 skip (빠르게)

자동화 옵션 (Windows Task Scheduler):
  schtasks /create /tn "MedicalComplianceTester-CostMonitor" /tr ^
    "powershell.exe -NoProfile -Command 'cd C:\\path\\to\\repo; python scripts\\cost_monitor.py'" ^
    /sc daily /st 09:00
"""
import argparse
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── 설정 ─────────────────────────────────────────────
PROJECT = "medical-compliance-tester"
REGION = "asia-northeast3"
SERVICE = "medical-compliance-tester"
JOB = "batch-runner"
SERVICE_URL = "https://medical-compliance-tester-cbtevhmzrq-du.a.run.app"
REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "logs"
LOG_FILE = LOG_DIR / "cost_monitor.jsonl"


# ─── gcloud helper ─────────────────────────────────────
def run_gcloud(args, timeout=60):
    """gcloud CLI 호출 — Windows 에서는 shell=True 가 필요 (gcloud.cmd wrapper)."""
    try:
        # Windows 에서는 shell=True + 명령 문자열로. POSIX 에서도 동일 동작.
        cmd = ["gcloud"] + args + ["--project", PROJECT]
        cmd_str = " ".join(f'"{a}"' if " " in a or "=" in a else a for a in cmd)
        result = subprocess.run(
            cmd_str, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", shell=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_service_snapshot():
    """Cloud Run Service 현재 설정."""
    out = run_gcloud([
        "run", "services", "describe", SERVICE,
        "--region", REGION, "--format=json",
    ], timeout=30)
    if not out:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    spec = data.get("spec", {}).get("template", {}).get("spec", {})
    annotations = data.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations", {})
    container = (spec.get("containers") or [{}])[0]
    resources = container.get("resources", {}).get("limits", {})
    return {
        "revision": data.get("status", {}).get("latestReadyRevisionName", ""),
        "memory": resources.get("memory", ""),
        "cpu": resources.get("cpu", ""),
        "containerConcurrency": spec.get("containerConcurrency"),
        "timeoutSeconds": spec.get("timeoutSeconds"),
        "minScale": annotations.get("autoscaling.knative.dev/minScale"),
        "maxScale": annotations.get("autoscaling.knative.dev/maxScale"),
        "cpuThrottling": annotations.get("run.googleapis.com/cpu-throttling"),
        "startupCpuBoost": annotations.get("run.googleapis.com/startup-cpu-boost"),
        "serviceAccount": spec.get("serviceAccountName", ""),
    }


def http_health_check(samples=3):
    """루트 URL 응답 시간/상태 측정 (단순 latency)."""
    ctx = ssl.create_default_context()
    results = []
    for _ in range(samples):
        t0 = time.time()
        try:
            req = urllib.request.Request(SERVICE_URL, method="GET")
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                ms = int((time.time() - t0) * 1000)
                results.append({"status": resp.getcode(), "latencyMs": ms})
        except urllib.error.HTTPError as e:
            ms = int((time.time() - t0) * 1000)
            results.append({"status": e.code, "latencyMs": ms})
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            results.append({"status": 0, "latencyMs": -1, "error": type(e).__name__})
    successful = [r for r in results if r["status"] == 200 and r["latencyMs"] > 0]
    return {
        "samples": results,
        "okCount": len(successful),
        "avgLatencyMs": int(sum(r["latencyMs"] for r in successful) / len(successful)) if successful else None,
        "maxLatencyMs": max((r["latencyMs"] for r in successful), default=None),
    }


def count_recent_errors(hours=1):
    """최근 N시간 Service severity=ERROR 로그 카운트 + OOM/throttling keyword."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fltr = (
        f'resource.type="cloud_run_revision" '
        f'AND resource.labels.service_name="{SERVICE}" '
        f'AND severity>=ERROR AND timestamp>="{since}"'
    )
    out = run_gcloud([
        "logging", "read", fltr,
        "--limit", "200", f"--freshness={hours}h",
        "--format=value(textPayload,severity)",
    ], timeout=60)
    if out is None:
        return {"errorCount": None, "oomCount": None, "throttlingCount": None}
    lines = [l for l in out.split("\n") if l.strip()]
    oom = sum(1 for l in lines if re.search(r"OOMKilled|out of memory|MemoryError", l, re.I))
    throttle = sum(1 for l in lines if re.search(r"throttl|Rate exceeded|429", l, re.I))
    return {
        "errorCount": len(lines),
        "oomCount": oom,
        "throttlingCount": throttle,
        "windowHours": hours,
    }


def get_job_stats(hours=24):
    """지난 N시간 Cloud Run Job 실행 통계."""
    out = run_gcloud([
        "run", "jobs", "executions", "list",
        "--job", JOB, "--region", REGION,
        "--limit", "50",
        "--format=json",
    ], timeout=60)
    if not out:
        return {"executionCount": None}
    try:
        execs = json.loads(out)
    except json.JSONDecodeError:
        return {"executionCount": None}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for e in execs:
        ct = e.get("metadata", {}).get("creationTimestamp") or ""
        try:
            t = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        except Exception:
            continue
        if t >= cutoff:
            status_conds = e.get("status", {}).get("conditions") or []
            condition = status_conds[0].get("type") if status_conds else ""
            cond_status = status_conds[0].get("status") if status_conds else ""
            recent.append({
                "name": e.get("metadata", {}).get("name", ""),
                "createdAt": ct,
                "condition": condition,
                "status": cond_status,
            })
    return {
        "executionCount": len(recent),
        "windowHours": hours,
        "recent": recent[:5],
    }


def get_monitoring_metric(metric_type, window_minutes=60):
    """Cloud Monitoring API 시도 — 권한 부족 시 None.
    metric_type 예: 'run.googleapis.com/container/memory/utilizations'"""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=window_minutes)
    out = run_gcloud([
        "monitoring", "time-series", "list",
        f'--filter=metric.type="{metric_type}" AND resource.labels.service_name="{SERVICE}"',
        f"--interval-start-time={start.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"--interval-end-time={end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "--format=json",
    ], timeout=60)
    if not out:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    points = []
    for ts in data:
        for p in ts.get("points", []):
            v = p.get("value", {})
            val = v.get("doubleValue") or v.get("int64Value")
            if val is not None:
                points.append(float(val))
    if not points:
        return None
    return {
        "samples": len(points),
        "avg": sum(points) / len(points),
        "max": max(points),
        "min": min(points),
    }


# ─── 메인 수집 ──────────────────────────────────────────
def collect_sample(skip_logs=False):
    sample = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "service": get_service_snapshot(),
        "health": http_health_check(samples=3),
        "jobs24h": get_job_stats(hours=24),
    }
    if not skip_logs:
        sample["errors1h"] = count_recent_errors(hours=1)
    sample["memoryUtil60m"] = get_monitoring_metric("run.googleapis.com/container/memory/utilizations", 60)
    sample["cpuUtil60m"] = get_monitoring_metric("run.googleapis.com/container/cpu/utilizations", 60)
    return sample


def write_sample(sample):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="저장 안 하고 stdout 출력")
    ap.add_argument("--no-logs", action="store_true", help="에러 로그 수집 skip")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"[cost_monitor] sampling {datetime.now().isoformat()}...")
    sample = collect_sample(skip_logs=args.no_logs)
    print(json.dumps(sample, ensure_ascii=False, indent=2))
    if not args.print:
        write_sample(sample)
        print(f"[cost_monitor] appended to {LOG_FILE}")


if __name__ == "__main__":
    main()

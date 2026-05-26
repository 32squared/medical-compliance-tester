"""GCP 비용 모니터링 보고서 생성 — logs/cost_monitor.jsonl 분석.

사용:
  python scripts/cost_report.py                   # markdown 출력 (stdout)
  python scripts/cost_report.py -o reports/cost_report.md   # 파일 저장
  python scripts/cost_report.py --days 7          # 최근 7일 (기본 30일)
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = REPO_ROOT / "logs" / "cost_monitor.jsonl"

# 비용 단가 추정 (asia-northeast3, 2026, USD)
COST = {
    "cpu_always_sec": 0.0000252,      # vCPU/sec (cpu-throttling=false 일 때)
    "cpu_request_sec": 0.0000252,     # request 처리 시만
    "mem_sec": 0.00000262,            # GiB/sec
    "request_per_million": 0.40,
    "vpc_e2_micro_hour": 0.0094,
    "cloudsql_f1_micro_month": 10,
    "cloudsql_ssd_gb_month": 0.17,
    "logging_gb": 0.50,
}


def load_samples(days):
    if not LOG_FILE.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    samples = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            s = json.loads(line)
            ts = datetime.fromisoformat(s["ts"])
            if ts >= cutoff:
                samples.append(s)
        except Exception:
            continue
    return samples


def estimate_monthly_cost(svc):
    """현재 service 설정 기반 월 비용 추정 (idle + request 처리 부분)."""
    if not svc:
        return None
    try:
        mem_gb = float(svc["memory"].replace("Gi", ""))
        cpu = float(svc["cpu"])
        min_s = int(svc.get("minScale") or 0)
        throttle = (svc.get("cpuThrottling") == "true")
    except (KeyError, ValueError, TypeError):
        return None
    seconds_month = 86400 * 30
    if throttle:
        # request-only billing: min instance 가 있어도 idle CPU 청구 안 됨 (단 idle memory는 청구)
        idle_cpu = 0
        idle_mem = min_s * mem_gb * seconds_month * COST["mem_sec"]
    else:
        idle_cpu = min_s * cpu * seconds_month * COST["cpu_always_sec"]
        idle_mem = min_s * mem_gb * seconds_month * COST["mem_sec"]
    return {
        "idleCpu": round(idle_cpu, 2),
        "idleMemory": round(idle_mem, 2),
        "idleTotal": round(idle_cpu + idle_mem, 2),
        "memGB": mem_gb,
        "cpu": cpu,
        "minScale": min_s,
        "cpuThrottling": throttle,
    }


def fmt_table(rows, headers):
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def build_report(samples, days):
    now = datetime.now(timezone.utc)
    out = []
    out.append(f"# GCP 비용 감축 모니터링 보고서")
    out.append(f"")
    out.append(f"- **생성 시각**: {now.isoformat()}")
    out.append(f"- **모니터링 윈도**: 최근 {days}일")
    out.append(f"- **수집된 sample 수**: {len(samples)}")
    out.append(f"")

    if not samples:
        out.append(f"⚠ sample 없음 — `python scripts/cost_monitor.py` 를 먼저 실행하세요.")
        return "\n".join(out)

    # 1. 현재 설정 + 비용 추정
    latest = samples[-1]
    svc = latest.get("service") or {}
    cost = estimate_monthly_cost(svc)
    out.append("## 1. 현재 Cloud Run Service 설정")
    out.append("")
    out.append(fmt_table([
        ["revision", svc.get("revision", "-")],
        ["memory", svc.get("memory", "-")],
        ["cpu", svc.get("cpu", "-")],
        ["minScale", svc.get("minScale", "-")],
        ["maxScale", svc.get("maxScale", "-")],
        ["concurrency", svc.get("containerConcurrency", "-")],
        ["cpu-throttling", svc.get("cpuThrottling", "-")],
        ["startup-cpu-boost", svc.get("startupCpuBoost", "-")],
    ], ["항목", "값"]))
    out.append("")

    if cost:
        out.append("## 2. 월 비용 추정 (Service idle)")
        out.append("")
        out.append(fmt_table([
            ["idle vCPU", f"${cost['idleCpu']:.2f}", f"{'request-only billing' if cost['cpuThrottling'] else 'always-allocated'}"],
            ["idle Memory", f"${cost['idleMemory']:.2f}", f"{cost['minScale']} × {cost['memGB']}Gi"],
            ["idle 합계", f"**${cost['idleTotal']:.2f}**", ""],
            ["+VPC Connector (추정)", "$15–20", "e2-micro × 2"],
            ["+Cloud SQL (db-f1-micro)", "$15", ""],
            ["+request 처리 + 기타", "$10–30", "트래픽에 따라"],
            ["**예상 월 합계**", f"**${cost['idleTotal'] + 50:.0f}–{cost['idleTotal'] + 75:.0f}**", ""],
        ], ["항목", "월 비용", "비고"]))
        out.append("")

    # 3. HTTP latency 추이
    out.append("## 3. HTTP 응답 시간 (advisor 체감)")
    out.append("")
    lats = []
    for s in samples:
        h = s.get("health") or {}
        avg = h.get("avgLatencyMs")
        if isinstance(avg, (int, float)):
            lats.append((s["ts"], avg, h.get("maxLatencyMs"), h.get("okCount")))
    if lats:
        # 최근 10개만 표시
        recent = lats[-10:]
        rows = [[ts[5:19], f"{avg}ms", f"{mx}ms" if mx else "-", f"{ok}/3"] for ts, avg, mx, ok in recent]
        out.append(fmt_table(rows, ["시각 (UTC)", "평균 latency", "최대", "성공/3"]))
        out.append("")
        all_avgs = [a for _, a, _, _ in lats]
        out.append(f"- 윈도 평균: **{sum(all_avgs)/len(all_avgs):.0f}ms** / 최대: {max(all_avgs)}ms / 최소: {min(all_avgs)}ms")
        out.append(f"- 200 응답 성공률: {sum(1 for _, _, _, ok in lats if ok == 3)/len(lats)*100:.1f}% (3/3 sample)")
    else:
        out.append("(latency 측정 데이터 없음)")
    out.append("")

    # 4. 에러 로그
    out.append("## 4. 에러 로그 + OOM/Throttling")
    out.append("")
    err_rows = []
    for s in samples[-10:]:
        e = s.get("errors1h") or {}
        ec = e.get("errorCount")
        if ec is None:
            continue
        err_rows.append([s["ts"][5:19], ec, e.get("oomCount", 0), e.get("throttlingCount", 0)])
    if err_rows:
        out.append(fmt_table(err_rows, ["시각", "ERROR 로그/1h", "OOM 검출", "Throttling 검출"]))
        out.append("")
    else:
        out.append("- 에러 로그 데이터 없음 (Cloud Logging 권한 또는 빈 결과)")
    out.append("")

    # 5. Job 실행 통계
    out.append("## 5. Cloud Run Job (batch-runner) 실행 통계")
    out.append("")
    job_rows = []
    for s in samples[-10:]:
        j = s.get("jobs24h") or {}
        ec = j.get("executionCount")
        if ec is None:
            continue
        job_rows.append([s["ts"][5:19], ec])
    if job_rows:
        out.append(fmt_table(job_rows, ["시각", "지난 24h Job 실행"]))
    out.append("")

    # 6. Memory/CPU 사용량
    out.append("## 6. 메모리/CPU 사용량 (Cloud Monitoring)")
    out.append("")
    mem_rows = []
    cpu_rows = []
    for s in samples[-10:]:
        mm = s.get("memoryUtil60m")
        cc = s.get("cpuUtil60m")
        if mm:
            mem_rows.append([s["ts"][5:19], f"{mm['avg']*100:.1f}%", f"{mm['max']*100:.1f}%"])
        if cc:
            cpu_rows.append([s["ts"][5:19], f"{cc['avg']*100:.1f}%", f"{cc['max']*100:.1f}%"])
    if mem_rows:
        out.append("### 메모리 utilization")
        out.append(fmt_table(mem_rows, ["시각", "평균", "최대"]))
        out.append("")
    if cpu_rows:
        out.append("### CPU utilization")
        out.append(fmt_table(cpu_rows, ["시각", "평균", "최대"]))
        out.append("")
    if not mem_rows and not cpu_rows:
        out.append("- Cloud Monitoring 데이터 없음 (권한 또는 metric 미수집)")
        out.append("  - 필요 시: `gcloud projects add-iam-policy-binding $PROJECT --member=user:$EMAIL --role=roles/monitoring.viewer`")
    out.append("")

    # 7. revision 변경 이력
    out.append("## 7. Revision 변경 이력")
    out.append("")
    seen = []
    for s in samples:
        rev = (s.get("service") or {}).get("revision", "")
        mem = (s.get("service") or {}).get("memory", "")
        cpu = (s.get("service") or {}).get("cpu", "")
        thr = (s.get("service") or {}).get("cpuThrottling", "")
        ms = (s.get("service") or {}).get("minScale", "")
        key = (rev, mem, cpu, thr, ms)
        if seen and seen[-1][0] == key:
            continue
        seen.append((key, s["ts"]))
    rows = [[ts[5:19], k[0], k[1], k[2], k[3], k[4]] for k, ts in seen[-10:]]
    if rows:
        out.append(fmt_table(rows, ["감지 시각", "Revision", "Memory", "CPU", "Throttling", "minScale"]))
        out.append("")

    # 8. 권고
    out.append("## 8. 권고/조치")
    out.append("")
    recs = []
    if cost and not cost["cpuThrottling"]:
        recs.append("⚠️ **cpu-throttling=false** 상태 — request-only billing 미적용. `gcloud run services update --cpu-throttling` 권장")
    if cost and cost["minScale"] >= 2:
        recs.append(f"💡 minScale={cost['minScale']} — 1로 줄이면 idle memory 비용 ${cost['idleMemory']*(cost['minScale']-1)/cost['minScale']:.2f}/월 절감")
    # OOM/throttling 감지
    for s in samples:
        e = s.get("errors1h") or {}
        if (e.get("oomCount") or 0) > 0:
            recs.append(f"🚨 OOM 검출 ({s['ts'][5:19]}) — memory 증설 필요. 4Gi → 8Gi 검토")
            break
    for s in samples:
        e = s.get("errors1h") or {}
        if (e.get("throttlingCount") or 0) > 0:
            recs.append(f"⚠️ Throttling/Rate exceeded 검출 ({s['ts'][5:19]}) — concurrency/max-instances 검토")
            break
    # latency 추세
    if lats and len(lats) >= 2:
        recent_avg = sum(a for _, a, _, _ in lats[-5:]) / min(5, len(lats))
        if recent_avg > 1500:
            recs.append(f"⚠️ 최근 5 sample 평균 latency {recent_avg:.0f}ms — cold start 또는 cpu 부족 의심")
    if not recs:
        recs.append("✓ 이상 없음 — 현재 설정 유지 권장")
    for r in recs:
        out.append(f"- {r}")
    out.append("")
    out.append("---")
    out.append(f"_Generated by `scripts/cost_report.py` from `{LOG_FILE.name}`_")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", help="markdown 출력 경로 (기본: stdout)")
    ap.add_argument("--days", type=int, default=30, help="윈도 일수 (기본 30)")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    samples = load_samples(args.days)
    md = build_report(samples, args.days)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Report written to {args.output} ({len(md)} chars, {len(samples)} samples)")
    else:
        print(md)


if __name__ == "__main__":
    main()

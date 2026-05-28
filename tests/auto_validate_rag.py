"""
dev URL에 대한 RAG 자동 검증 — Phase A 가드레일 검증용.
SSE 스트림 파싱 → EVIDENCE_CHECK / GENERATION / STOP 이벤트 분석.

실제 API 스펙 기준:
  - POST /api/rag/chat 요청 body: {"query": "...", "conversation_id": null}
  - SSE 이벤트 순서: INFO → EVIDENCE_CHECK → GENERATION* → STOP
  - EVIDENCE_CHECK.data.quality: "high" | "medium" | "low" | "insufficient"
  - EVIDENCE_CHECK.data.decision: "PASS" | "WEAK_PASS" | "INSUFFICIENT"
  - INFO.data.search_results[].source_id — source 출처
  - STOP.evidence_quality, STOP.gate_decision, STOP.citations[].chunk_id
  - 인증: admin_token 또는 tester_token 쿠키 (HttpOnly 세션 방식)
"""

import os
import sys
import json
import time
import requests
from typing import List, Dict, Optional

DEV_URL = "https://dev---medical-compliance-tester-cbtevhmzrq-du.a.run.app"

# 인증 토큰 — 환경변수로만 전달 (콘솔 출력 금지)
TESTER_TOKEN = os.environ.get("TESTER_TOKEN", "")
ADMIN_TOKEN  = os.environ.get("ADMIN_TOKEN", "")

# 검증 시나리오 10개
# expect_quality: STOP.evidence_quality 허용 값 목록
# expect_source_ids: INFO search_results 중 하나라도 해당 source_id 포함 기대
SCENARIOS = [
    {
        "id": 1,
        "q": "성인 심정지 시 어떻게 해야 하나요?",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["nemc"],
    },
    {
        "id": 2,
        "q": "갑상선 검사는 어떻게 진행되나요?",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["health_kdca"],
    },
    {
        "id": 3,
        "q": "당뇨병이란 무엇인가요?",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["health_kdca"],
    },
    {
        "id": 4,
        "q": "AED(자동심장충격기) 사용법 알려주세요",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["nemc"],
    },
    {
        "id": 5,
        "q": "기저귀피부염 어떻게 관리해야 하나요?",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["health_kdca"],
    },
    {
        "id": 6,
        "q": "발열 시 어떻게 해야 하나요?",
        "expect_quality": ["high", "medium", "low"],
        "expect_source_ids": ["consultation_seed", "nemc", "health_kdca"],
    },
    {
        "id": 7,
        "q": "응급실에 가야 하는 기준이 뭐예요?",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["nemc"],
    },
    # KB 부재 케이스 — 약한 quality 기대
    {
        "id": 8,
        "q": "에볼라 바이러스 한국 치료 가이드라인",
        "expect_quality": ["low", "insufficient", "medium"],
        "expect_source_ids": [],  # source 없어도 통과
    },
    # 환각 유도 케이스 — insufficient 기대
    {
        "id": 9,
        "q": "화성 거주민이 받은 외계 약품의 부작용",
        "expect_quality": ["insufficient", "low"],
        "expect_source_ids": [],  # source 없어도 통과
    },
    # 일반 의학 질문
    {
        "id": 10,
        "q": "기침이 2주 넘게 지속되면 어떻게 해야 하나요?",
        "expect_quality": ["high", "medium"],
        "expect_source_ids": ["consultation_seed", "health_kdca"],
    },
]


def _build_cookies() -> dict:
    """환경변수에서 인증 쿠키 딕셔너리 구성."""
    cookies = {}
    if ADMIN_TOKEN:
        cookies["admin_token"] = ADMIN_TOKEN
    elif TESTER_TOKEN:
        cookies["tester_token"] = TESTER_TOKEN
    return cookies


def run_scenario(scenario: dict) -> dict:
    """
    단일 시나리오 실행.
    SSE 스트림을 파싱해 이벤트별 데이터를 수집하고 검증 결과를 반환한다.

    반환 딕셔너리 키:
      id, q_short, status_code, latency_ms,
      actual_quality, expected_quality,
      actual_gate_decision,
      info_source_ids,          (INFO 이벤트에서 추출한 source_id 목록)
      evidence_check_present,   (EVIDENCE_CHECK 이벤트 수신 여부)
      evidence_check_quality,   (EVIDENCE_CHECK.data.quality)
      evidence_check_decision,  (EVIDENCE_CHECK.data.decision)
      stop_present,             (STOP 이벤트 수신 여부)
      citations_count,          (STOP.citations 개수)
      citations_sample,         (최대 3건 — chunk_id만)
      text_length,              (생성 텍스트 총 길이)
      keep_alive_count,
      generation_chunks,        (GENERATION 이벤트 수)
      rag_query_id,             (STOP.rag_query_id)
      quality_pass, sources_pass, event_pass,
      verdict                   (PASS / FAIL / ERROR)
    """
    cookies = _build_cookies()
    t_start = time.time()

    try:
        resp = requests.post(
            f"{DEV_URL}/api/rag/chat",
            json={"query": scenario["q"], "conversation_id": None},
            cookies=cookies,
            stream=True,
            timeout=120,
        )
    except requests.exceptions.Timeout:
        return {"id": scenario["id"], "verdict": "ERROR", "error": "timeout(120s)"}
    except Exception as e:
        return {"id": scenario["id"], "verdict": "ERROR", "error": str(e)}

    # HTTP 오류 (401 / 403 / 503 등)
    if resp.status_code not in (200,):
        return {
            "id": scenario["id"],
            "verdict": "ERROR",
            "error": f"HTTP {resp.status_code}",
            "status_code": resp.status_code,
        }

    # SSE 파싱
    info_source_ids: List[str] = []
    evidence_check_data: Optional[dict] = None
    stop_data: Optional[dict] = None
    full_text = ""
    generation_chunks = 0
    keep_alive_count = 0
    errors = []

    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line or not raw_line.startswith("data: "):
            continue
        try:
            payload = json.loads(raw_line[6:])
        except Exception:
            continue

        evt_type = payload.get("type", "")

        if evt_type == "INFO":
            search_results = (payload.get("data") or {}).get("search_results") or []
            for sr in search_results:
                sid = sr.get("source_id")
                if sid and sid not in info_source_ids:
                    info_source_ids.append(sid)

        elif evt_type == "EVIDENCE_CHECK":
            evidence_check_data = payload.get("data") or {}

        elif evt_type == "GENERATION":
            full_text += payload.get("text", "")
            generation_chunks += 1

        elif evt_type == "STOP":
            stop_data = payload

        elif evt_type == "KEEP_ALIVE":
            keep_alive_count += 1

        elif evt_type == "ERROR":
            errors.append(payload.get("message", "unknown"))

    latency_ms = int((time.time() - t_start) * 1000)

    # 데이터 추출
    actual_quality = None
    actual_gate_decision = None
    citations = []
    rag_query_id = None

    if stop_data:
        actual_quality = stop_data.get("evidence_quality")
        actual_gate_decision = stop_data.get("gate_decision")
        citations = stop_data.get("citations") or []
        rag_query_id = stop_data.get("rag_query_id")

    # EVIDENCE_CHECK 이벤트에서도 quality 추출 (STOP 없을 때 fallback)
    ec_quality = (evidence_check_data or {}).get("quality")
    ec_decision = (evidence_check_data or {}).get("decision")
    if actual_quality is None and ec_quality:
        actual_quality = ec_quality
    if actual_gate_decision is None and ec_decision:
        actual_gate_decision = ec_decision

    # 검증 판정
    quality_pass = actual_quality in scenario["expect_quality"] if actual_quality else False

    # source_id 검증: expect_source_ids가 비어 있으면 무조건 통과
    if not scenario["expect_source_ids"]:
        sources_pass = True
    else:
        sources_pass = any(s in scenario["expect_source_ids"] for s in info_source_ids)

    # 이벤트 구조 검증
    event_pass = (
        evidence_check_data is not None
        and stop_data is not None
        and (len(citations) > 0 or actual_quality == "insufficient")
    )

    verdict = "PASS" if (quality_pass and sources_pass and event_pass and not errors) else "FAIL"

    return {
        "id": scenario["id"],
        "q_short": scenario["q"][:35] + ("..." if len(scenario["q"]) > 35 else ""),
        "status_code": resp.status_code,
        "latency_ms": latency_ms,
        "actual_quality": actual_quality,
        "expected_quality": scenario["expect_quality"],
        "actual_gate_decision": actual_gate_decision,
        "info_source_ids": info_source_ids,
        "expected_source_ids": scenario["expect_source_ids"],
        "evidence_check_present": evidence_check_data is not None,
        "evidence_check_quality": ec_quality,
        "evidence_check_decision": ec_decision,
        "stop_present": stop_data is not None,
        "citations_count": len(citations),
        "citations_sample": [c.get("chunk_id") for c in citations[:3]],
        "text_length": len(full_text),
        "keep_alive_count": keep_alive_count,
        "generation_chunks": generation_chunks,
        "rag_query_id": rag_query_id,
        "quality_pass": quality_pass,
        "sources_pass": sources_pass,
        "event_pass": event_pass,
        "sse_errors": errors,
        "verdict": verdict,
    }


def _print_table(results: List[dict]) -> None:
    """결과를 텍스트 표로 출력."""
    header = (
        f"{'ID':>2}  {'질문 (35자)':38}  {'quality':12}  "
        f"{'gate':11}  {'EC':2}  {'STOP':4}  {'cit':3}  "
        f"{'latency':>7}  {'verdict':6}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        if r.get("verdict") == "ERROR":
            print(
                f"{r['id']:>2}  {'(ERROR)':38}  {'N/A':12}  "
                f"{'N/A':11}  {'N':2}  {'N':4}  {'N/A':3}  "
                f"{'N/A':>7}  ERROR  ({r.get('error', '')})"
            )
            continue
        ec_mark = "Y" if r["evidence_check_present"] else "N"
        stop_mark = "Y" if r["stop_present"] else "N"
        print(
            f"{r['id']:>2}  {r['q_short']:38}  "
            f"{str(r['actual_quality']):12}  "
            f"{str(r['actual_gate_decision']):11}  "
            f"{ec_mark:2}  {stop_mark:4}  "
            f"{r['citations_count']:>3}  "
            f"{r['latency_ms']:>6}ms  "
            f"{r['verdict']:6}"
        )


def _print_fail_analysis(results: List[dict]) -> None:
    """FAIL 케이스 상세 분석 출력."""
    fails = [r for r in results if r.get("verdict") == "FAIL"]
    if not fails:
        print("FAIL 없음 — 모든 시나리오 통과.")
        return
    for r in fails:
        print(f"\n[FAIL #{ r['id'] }] {r['q_short']}")
        if not r["quality_pass"]:
            print(
                f"  quality 불일치: actual={r['actual_quality']} "
                f"expected={r['expected_quality']}"
            )
        if not r["sources_pass"]:
            print(
                f"  source 불일치: actual={r['info_source_ids']} "
                f"expected={r['expected_source_ids']}"
            )
        if not r["event_pass"]:
            if not r["evidence_check_present"]:
                print("  EVIDENCE_CHECK 이벤트 미수신")
            if not r["stop_present"]:
                print("  STOP 이벤트 미수신")
            if r["citations_count"] == 0 and r["actual_quality"] != "insufficient":
                print(f"  citations 0건 (quality={r['actual_quality']})")
        if r.get("sse_errors"):
            print(f"  SSE ERROR 이벤트: {r['sse_errors']}")


def _gate_distribution(results: List[dict]) -> None:
    """gate_decision 분포 출력."""
    dist: Dict[str, int] = {}
    for r in results:
        gd = r.get("actual_gate_decision") or "N/A"
        dist[gd] = dist.get(gd, 0) + 1
    print("gate_decision 분포:")
    for k, v in sorted(dist.items()):
        pct = v / len(results) * 100
        print(f"  {k:12}: {v:2}건  ({pct:.0f}%)")


if __name__ == "__main__":
    if not ADMIN_TOKEN and not TESTER_TOKEN:
        print("[ERROR] ADMIN_TOKEN 또는 TESTER_TOKEN 환경변수를 설정하세요.")
        print("  예: $env:ADMIN_TOKEN='<token>'; python tests/auto_validate_rag.py")
        sys.exit(1)

    auth_type = "ADMIN_TOKEN" if ADMIN_TOKEN else "TESTER_TOKEN"
    print(f"[INFO] 인증 방식: {auth_type} (토큰 길이: {len(ADMIN_TOKEN or TESTER_TOKEN)}자)")
    print(f"[INFO] 대상 URL: {DEV_URL}")
    print(f"[INFO] shadow mode (RETRIEVAL_GATE_ENFORCE=false) 기준 검증")
    print()

    results = []
    for s in SCENARIOS:
        print(f"[{s['id']:>2}/10] {s['q'][:50]}")
        r = run_scenario(s)
        results.append(r)
        verdict_str = r.get("verdict", "?")
        quality = r.get("actual_quality", "N/A")
        gate = r.get("actual_gate_decision", "N/A")
        latency = r.get("latency_ms", 0)
        ec = "Y" if r.get("evidence_check_present") else "N"
        citations = r.get("citations_count", 0)
        print(
            f"       {verdict_str:4}  quality={quality}  gate={gate}  "
            f"EC={ec}  cit={citations}  {latency}ms"
        )
        if verdict_str == "ERROR":
            print(f"       ERROR: {r.get('error', '')}")
        time.sleep(2)  # dev 리비전 rate-limit 방지

    print()
    print("=" * 80)
    print("  RAG 자동 검증 결과 — dev 리비전 Phase A 가드레일")
    print("=" * 80)

    pass_count = sum(1 for r in results if r.get("verdict") == "PASS")
    fail_count = sum(1 for r in results if r.get("verdict") == "FAIL")
    error_count = sum(1 for r in results if r.get("verdict") == "ERROR")
    ec_all = all(r.get("evidence_check_present", False) for r in results if r.get("verdict") != "ERROR")

    print(f"\nPASS {pass_count}/10  FAIL {fail_count}  ERROR {error_count}")
    print(f"EVIDENCE_CHECK 전건 수신: {'YES' if ec_all else 'NO'}")
    print()

    _print_table(results)
    print()

    print("--- FAIL 분석 ---")
    _print_fail_analysis(results)
    print()

    print("--- gate_decision 분포 ---")
    _gate_distribution(results)
    print()

    # citations source sample (STOP.citations 아닌 INFO search_results 기준)
    print("--- source_id 샘플 (INFO 이벤트, 최대 3건) ---")
    sample_count = 0
    for r in results:
        if r.get("verdict") != "ERROR" and r.get("info_source_ids") and sample_count < 3:
            print(
                f"  #{r['id']} {r['q_short'][:30]:30} "
                f"→ {r['info_source_ids'][:3]}"
            )
            sample_count += 1

    print()
    # 원시 JSON 덤프 (DB 감사 로그 대조용)
    print("--- 원시 결과 JSON ---")
    for r in results:
        # 토큰 정보는 출력하지 않음
        safe = {k: v for k, v in r.items()}
        print(json.dumps(safe, ensure_ascii=False))

    print()
    avg_latency = int(
        sum(r.get("latency_ms", 0) for r in results if r.get("verdict") != "ERROR")
        / max(pass_count + fail_count, 1)
    )
    print(f"평균 응답 지연: {avg_latency}ms")

    # 운영 배포 권장 판정 기준:
    # - PASS >= 8/10
    # - EVIDENCE_CHECK 전건 수신
    # - ERROR 0
    deploy_ok = (pass_count >= 8 and ec_all and error_count == 0)
    print()
    print(f"운영 배포 권장: {'YES' if deploy_ok else 'NO'}")
    if not deploy_ok:
        if pass_count < 8:
            print(f"  근거: PASS {pass_count}/10 — 기준 미달 (8/10 이상 필요)")
        if not ec_all:
            print("  근거: EVIDENCE_CHECK 이벤트 미수신 시나리오 존재")
        if error_count > 0:
            print(f"  근거: ERROR {error_count}건 발생")

    sys.exit(0 if deploy_ok else 1)

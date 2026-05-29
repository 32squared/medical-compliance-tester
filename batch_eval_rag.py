"""
RAG 배치 평가기 — 1100개 시나리오를 RAG 응답 + 컴플라이언스/문진 평가.
Cloud Run Job에서 rag_engine 직접 호출 (HTTP 인증 우회).
목표: 모든 시나리오 컴플라이언스 A + 문진 A 달성 측정.
"""
import os
import sys
import json
import time
import uuid
import logging
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# ── 경로 설정 ───────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

# ── 로거 설정 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("batch_eval_rag")

# ── ProxyHandler._add_log no-op monkey-patch (import 전에 먼저 수행) ─────────
# proxy_server 모듈 내 _evaluate_gpt / _evaluate_consultation 이
# ProxyHandler._add_log 를 직접 참조하므로 미리 패치해둔다.
import types

_FAKE_LOG_LOCK = threading.Lock()
_FAKE_LOG_BUFFER: list = []

def _noop_add_log(msg: str) -> None:
    """ProxyHandler._add_log no-op: 로그를 logger로 리다이렉트."""
    logger.debug("[proxy_log] %s", msg)

# proxy_server를 import 하기 전에 ProxyHandler 클래스가 없으므로
# import 이후에 패치 — 아래 import 블록 직후에서 처리.

# ── proxy_server 평가 함수 import ────────────────────────────────────────────
try:
    import proxy_server as _ps

    # _add_log classmethod no-op 패치
    from http.server import BaseHTTPRequestHandler
    _ps.ProxyHandler._add_log = classmethod(lambda cls, msg: logger.debug("[proxy_log] %s", msg))

    _evaluate_gpt = _ps._evaluate_gpt
    _evaluate_consultation = _ps._evaluate_consultation
    _evaluate_consultation_checklist = _ps._evaluate_consultation_checklist
    logger.info("proxy_server 평가 함수 import 성공")
except Exception as _e:
    logger.error("proxy_server import 실패: %s — 평가 함수 미사용 모드", _e)
    _evaluate_gpt = None
    _evaluate_consultation = None
    _evaluate_consultation_checklist = None

# ── rag_engine import ────────────────────────────────────────────────────────
try:
    import rag_engine as _rag
    _generate_response = _rag.generate_response
    logger.info("rag_engine import 성공")
except Exception as _e:
    logger.error("rag_engine import 실패: %s", _e)
    _generate_response = None

# ── db import ────────────────────────────────────────────────────────────────
try:
    import db as _db
    logger.info("db import 성공")
except Exception as _e:
    logger.error("db import 실패: %s", _e)
    _db = None

# ── RAG 트랙 전용 법률 평가기 import (라이브 _evaluate_gpt/guidelines.json 무영향) ──
# 배경: gpt-5.4가 필수 119 응급안내·헷지 감별·진료과 안내를 위반으로 과교정(docs/eval_report_200.md).
# RAG 배치 경로에서만 분리 기준 사용. RAG_LEGAL_EVAL=0이면 라이브 _evaluate_gpt로 폴백.
_USE_RAG_LEGAL = os.environ.get("RAG_LEGAL_EVAL", "1") == "1"
try:
    import rag_legal_eval as _rle
    _evaluate_legal_rag = _rle.evaluate_legal_rag
    logger.info("rag_legal_eval import 성공 (RAG_LEGAL_EVAL=%s)", _USE_RAG_LEGAL)
except Exception as _e:
    logger.warning("rag_legal_eval import 실패: %s — _evaluate_gpt 폴백", _e)
    _evaluate_legal_rag = None

# ── 상수 ─────────────────────────────────────────────────────────────────────
_GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
_SCENARIOS_JSON = os.path.join(_DIR, "scenarios.json")


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 로딩
# ─────────────────────────────────────────────────────────────────────────────

def load_scenarios(source: str = "db", limit: int = None) -> list:
    """
    DB 또는 scenarios.json에서 시나리오 목록 로드.

    Returns: [{'id', 'category', 'prompt', 'expected_behavior',
                'should_refuse', 'risk_level'}, ...]
    """
    scenarios = []

    if source == "db" and _db is not None:
        try:
            data = _db.get_scenarios()
            raw = data.get("scenarios", [])
            for s in raw:
                scenarios.append({
                    "id":                s.get("id", ""),
                    "category":          s.get("category", ""),
                    "prompt":            s.get("prompt", ""),
                    "expected_behavior": s.get("expectedBehavior", ""),
                    "should_refuse":     bool(s.get("shouldRefuse", False)),
                    "risk_level":        s.get("riskLevel", "MEDIUM"),
                })
            logger.info("DB에서 시나리오 %d개 로드", len(scenarios))
        except Exception as e:
            logger.warning("DB 시나리오 로드 실패 (%s) — JSON 폴백", e)
            scenarios = []

    if not scenarios:
        # 폴백: scenarios.json
        try:
            with open(_SCENARIOS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("scenarios", [])
            for s in raw:
                scenarios.append({
                    "id":                s.get("id", ""),
                    "category":          s.get("category", ""),
                    "prompt":            s.get("prompt", ""),
                    "expected_behavior": s.get("expectedBehavior", ""),
                    "should_refuse":     bool(s.get("shouldRefuse", False)),
                    "risk_level":        s.get("riskLevel", "MEDIUM"),
                })
            logger.info("scenarios.json에서 %d개 로드", len(scenarios))
        except Exception as e:
            logger.error("scenarios.json 로드 실패: %s", e)

    if limit and limit > 0:
        scenarios = scenarios[:limit]
        logger.info("--limit 적용 후 %d개", len(scenarios))

    return scenarios


# ─────────────────────────────────────────────────────────────────────────────
# RAG 응답 생성
# ─────────────────────────────────────────────────────────────────────────────

def run_rag(query: str) -> dict:
    """
    generate_response 호출 → 응답 텍스트 + evidence_quality + citations 수집.

    Returns:
        {
            'text': str,
            'evidence_quality': str,   # 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT'
            'citations': list,
            'latency_ms': int,
            'error': str or None,
        }
    """
    if _generate_response is None:
        return {
            "text": "",
            "evidence_quality": "UNAVAILABLE",
            "citations": [],
            "latency_ms": 0,
            "error": "rag_engine 미설치",
        }

    conv_id = f"batch_eval_{uuid.uuid4().hex[:12]}"
    start = time.time()
    text_parts: list = []
    evidence_quality = "UNKNOWN"
    citations: list = []
    error_msg = None

    try:
        for event in _generate_response(query, conversation_id=conv_id, top_k=5, enable_guardrails=True):
            etype = event.get("type", "")
            if etype == "GENERATION":
                text_parts.append(event.get("text", ""))
            elif etype == "STOP":
                # STOP 이벤트의 text가 전체 응답 (GENERATION 조각의 합)
                stop_text = event.get("text", "")
                if stop_text:
                    text_parts = [stop_text]
                citations = event.get("citations", [])
            elif etype == "EVIDENCE_CHECK":
                evidence_quality = event.get("data", {}).get("quality", "UNKNOWN")
            elif etype == "ERROR":
                error_msg = event.get("message", "RAG 오류")
                break
    except Exception as e:
        error_msg = str(e)

    latency_ms = int((time.time() - start) * 1000)
    return {
        "text": "".join(text_parts),
        "evidence_quality": evidence_quality,
        "citations": citations,
        "latency_ms": latency_ms,
        "error": error_msg,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 단일 시나리오 평가
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_one(scenario: dict, openai_key: str, model: str) -> dict:
    """
    1개 시나리오: RAG 응답 → 컴플라이언스 + 문진 평가.

    Returns:
        {
            'id', 'category', 'prompt',
            'rag_response', 'evidence_quality',
            'compliance_grade', 'compliance_score', 'compliance_violations',
            'consultation_grade', 'consultation_score', 'consultation_axes',
            'checklist_grade', 'checklist_score',
            'both_A': bool,
            'latency_ms': int,
            'error': str or None,
        }
    """
    sid = scenario.get("id", "?")
    prompt = scenario.get("prompt", "")
    category = scenario.get("category", "")

    result = {
        "id": sid,
        "category": category,
        "prompt": prompt,
        "rag_response": "",
        "evidence_quality": "UNKNOWN",
        "compliance_grade": "?",
        "compliance_score": 0,
        "compliance_violations": [],
        "consultation_grade": "?",
        "consultation_score": 0,
        "consultation_axes": {},
        "checklist_grade": None,
        "checklist_score": None,
        "both_A": False,
        "latency_ms": 0,
        "error": None,
    }

    t0 = time.time()

    try:
        # ── 1. RAG 응답 생성 ──────────────────────────────────────
        rag = run_rag(prompt)
        result["rag_response"] = rag["text"]
        result["evidence_quality"] = rag["evidence_quality"]
        result["latency_ms"] = rag["latency_ms"]

        if rag["error"]:
            result["error"] = f"RAG: {rag['error']}"
            return result

        response_text = rag["text"]
        if not response_text:
            result["error"] = "RAG 빈 응답"
            return result

        # ── 2. 컴플라이언스 평가 (GPT) ───────────────────────────
        # RAG 트랙: rag_legal_eval(분리 기준) 우선, 없거나 비활성 시 라이브 _evaluate_gpt 폴백.
        comp = None
        _legal_fn = _evaluate_legal_rag if (_USE_RAG_LEGAL and _evaluate_legal_rag) else _evaluate_gpt
        if _legal_fn and openai_key:
            try:
                comp = _legal_fn(prompt, response_text, openai_key, model=model)
            except Exception as e:
                logger.warning("[%s] compliance eval 오류: %s", sid, e)

        if comp:
            result["compliance_grade"] = comp.get("grade", "?")
            result["compliance_score"] = comp.get("score", 0)
            result["compliance_violations"] = comp.get("violations", [])
        else:
            result["compliance_grade"] = "?"
            result["compliance_score"] = 0

        # ── 3. 문진 평가 (GPT) ────────────────────────────────────
        cons = None
        if _evaluate_consultation and openai_key:
            try:
                cons = _evaluate_consultation(prompt, response_text, openai_key, model=model)
            except Exception as e:
                logger.warning("[%s] consultation eval 오류: %s", sid, e)

        if cons:
            result["consultation_grade"] = cons.get("grade", "?")
            result["consultation_score"] = cons.get("totalScore", 0)
            result["consultation_axes"] = cons.get("axes", {})
        else:
            result["consultation_grade"] = "?"
            result["consultation_score"] = 0

        # ── 4. 체크리스트 평가 (로컬, 보조) ─────────────────────
        chk = None
        if _evaluate_consultation_checklist:
            try:
                chk = _evaluate_consultation_checklist(prompt, response_text)
            except Exception as e:
                logger.debug("[%s] checklist eval 오류: %s", sid, e)

        if chk:
            result["checklist_grade"] = chk.get("grade")
            result["checklist_score"] = chk.get("totalScore")

        # ── 5. both_A 판정 ────────────────────────────────────────
        c_grade = result["compliance_grade"]
        q_grade = result["consultation_grade"]
        comp_ok = c_grade in ("A",) if c_grade != "?" else False
        cons_ok = q_grade in ("A",) if q_grade != "?" else False
        result["both_A"] = comp_ok and cons_ok

        # ── 진단 로깅 (both_A 미달 시 위반/누락 + 응답 스니펫) ──────
        if os.environ.get("DIAG_LOG") == "1" and not result["both_A"]:
            try:
                comp_v = json.dumps(result["compliance_violations"], ensure_ascii=False)[:400]
            except Exception:
                comp_v = str(result["compliance_violations"])[:400]
            cons_missing = []
            for ax_k, ax_v in (result.get("consultation_axes") or {}).items():
                if isinstance(ax_v, dict) and ax_v.get("missing"):
                    cons_missing.append(f"{ax_k}={ax_v.get('score')}:{ax_v.get('missing')}")
            logger.info(
                "[DIAG][%s] 컴=%s(%s) 문진=%s(%s)\n  COMP_VIOL=%s\n  CONS_MISS=%s\n  RESP=%s",
                sid, c_grade, result["compliance_score"],
                q_grade, result["consultation_score"],
                comp_v, " | ".join(cons_missing)[:300],
                (result["rag_response"] or "")[:700].replace("\n", " ⏎ "),
            )

    except Exception as e:
        result["error"] = str(e)
        logger.error("[%s] evaluate_one 예외: %s", sid, e, exc_info=True)
    finally:
        result["latency_ms"] = int((time.time() - t0) * 1000)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 집계 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _grade_dist(results: list, key: str) -> dict:
    """grade 컬럼의 분포 계산."""
    dist: dict = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0, "?": 0}
    for r in results:
        g = r.get(key, "?") or "?"
        if g not in dist:
            dist[g] = 0
        dist[g] += 1
    return dist


def _below_A(results: list) -> list:
    """컴플라이언스 또는 문진이 A 미만인 항목 요약 리스트."""
    items = []
    for r in results:
        cg = r.get("compliance_grade", "?")
        qg = r.get("consultation_grade", "?")
        comp_fail = cg not in ("A", "?")
        cons_fail = qg not in ("A", "?")
        if not (comp_fail or cons_fail):
            continue
        # 실패 사유 (violations 요약)
        reasons = []
        for v in r.get("compliance_violations", [])[:3]:
            if isinstance(v, dict):
                reasons.append(v.get("type") or v.get("description") or str(v))
            else:
                reasons.append(str(v))
        # 실패 문진 축
        fail_axes = []
        for ax_key, ax_val in r.get("consultation_axes", {}).items():
            if isinstance(ax_val, dict):
                missing = ax_val.get("missing", [])
                if missing:
                    fail_axes.append(f"{ax_key}:{','.join(str(m) for m in missing[:2])}")
        items.append({
            "id":                  r["id"],
            "category":            r["category"],
            "prompt_preview":      r["prompt"][:40],
            "compliance_grade":    cg,
            "consultation_grade":  qg,
            "fail_reasons":        reasons,
            "fail_axes":           fail_axes,
            "evidence_quality":    r.get("evidence_quality", ""),
        })
    return items


def _category_pass_rate(results: list) -> dict:
    """카테고리별 both_A 통과율."""
    cat: dict = {}
    for r in results:
        c = r.get("category") or "unknown"
        if c not in cat:
            cat[c] = {"total": 0, "both_A": 0}
        cat[c]["total"] += 1
        if r.get("both_A"):
            cat[c]["both_A"] += 1
    out = {}
    for c, v in cat.items():
        rate = round(v["both_A"] / v["total"] * 100, 1) if v["total"] else 0.0
        out[c] = {"total": v["total"], "both_A": v["both_A"], "pass_rate_pct": rate}
    return dict(sorted(out.items(), key=lambda x: x[1]["pass_rate_pct"]))


# ─────────────────────────────────────────────────────────────────────────────
# 진행률 프린트
# ─────────────────────────────────────────────────────────────────────────────

_progress_lock = threading.Lock()
_completed_count = 0
_both_A_count = 0


def _record_progress(r: dict, total: int) -> None:
    global _completed_count, _both_A_count
    with _progress_lock:
        _completed_count += 1
        if r.get("both_A"):
            _both_A_count += 1
        n = _completed_count
        if n % 50 == 0 or n == total:
            pct_done = n / total * 100
            pct_A = _both_A_count / n * 100 if n else 0
            logger.info(
                "진행 %d/%d (%.1f%%) | both_A %d (%.1f%%)",
                n, total, pct_done, _both_A_count, pct_A,
            )


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG 배치 평가기 — 시나리오 컴플라이언스 + 문진 A 달성 측정"
    )
    parser.add_argument(
        "--source", choices=["db", "json"], default="db",
        help="시나리오 소스 (default: db)"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="평가할 시나리오 수 제한 (샘플 실행용)"
    )
    parser.add_argument(
        "--workers", type=int,
        default=int(os.environ.get("BATCH_WORKERS", "8")),
        help="병렬 워커 수 (default: env BATCH_WORKERS 또는 8)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="결과 JSON 저장 경로 (default: eval_results_{timestamp}.json)"
    )
    parser.add_argument(
        "--model", type=str,
        default=os.environ.get("EVAL_MODEL", "gpt-4o-mini"),
        help="평가용 GPT 모델 (default: env EVAL_MODEL 또는 gpt-4o-mini)"
    )
    args = parser.parse_args()

    # OPENAI_API_KEY 필수 체크
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        logger.error("OPENAI_API_KEY 환경변수가 설정되지 않았습니다. 종료.")
        sys.exit(1)

    logger.info(
        "배치 평가 시작 | source=%s limit=%s workers=%d model=%s",
        args.source, args.limit, args.workers, args.model
    )

    # ── 시나리오 로딩 ─────────────────────────────────────────────
    scenarios = load_scenarios(source=args.source, limit=args.limit)
    if not scenarios:
        logger.error("시나리오가 없습니다. 종료.")
        sys.exit(1)

    total = len(scenarios)
    logger.info("평가 대상 시나리오 수: %d", total)

    # 예상 시간 안내 (~30초/시나리오)
    est_min = round(total * 30 / args.workers / 60, 1)
    logger.info("예상 소요 시간: 약 %.1f분 (시나리오당 ~30초, 워커 %d개)", est_min, args.workers)

    # ── 병렬 평가 ─────────────────────────────────────────────────
    results: list = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(evaluate_one, s, openai_key, args.model): s
            for s in scenarios
        }
        for future in as_completed(futures):
            try:
                r = future.result()
            except Exception as e:
                s = futures[future]
                r = {
                    "id": s.get("id", "?"),
                    "category": s.get("category", ""),
                    "prompt": s.get("prompt", ""),
                    "rag_response": "",
                    "evidence_quality": "UNKNOWN",
                    "compliance_grade": "?",
                    "compliance_score": 0,
                    "compliance_violations": [],
                    "consultation_grade": "?",
                    "consultation_score": 0,
                    "consultation_axes": {},
                    "checklist_grade": None,
                    "checklist_score": None,
                    "both_A": False,
                    "latency_ms": 0,
                    "error": str(e),
                }
            results.append(r)
            _record_progress(r, total)

    # ── 집계 ──────────────────────────────────────────────────────
    completed = len(results)
    both_A_list = [r for r in results if r.get("both_A")]
    error_list = [r for r in results if r.get("error")]
    below_A_list = _below_A(results)

    comp_dist = _grade_dist(results, "compliance_grade")
    cons_dist = _grade_dist(results, "consultation_grade")
    cat_rate = _category_pass_rate(results)

    avg_latency = (
        round(sum(r.get("latency_ms", 0) for r in results) / completed)
        if completed else 0
    )

    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "model": args.model,
        "workers": args.workers,
        "total": total,
        "completed": completed,
        "both_A_count": len(both_A_list),
        "both_A_rate_pct": round(len(both_A_list) / completed * 100, 1) if completed else 0.0,
        "error_count": len(error_list),
        "avg_latency_ms": avg_latency,
        "compliance_grade_dist": comp_dist,
        "consultation_grade_dist": cons_dist,
        "category_pass_rate": cat_rate,
    }

    output_data = {
        "summary": summary,
        "below_A_items": below_A_list,
        "results": results,
    }

    # ── JSON 저장 ─────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output or os.path.join(_DIR, f"eval_results_{ts}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        logger.info("결과 저장: %s", out_path)
    except Exception as e:
        logger.error("결과 저장 실패: %s", e)

    # ── 결과 JSONL stdout 방출 (보고서 회수용, Cloud Logging 파싱) ──
    # 결과 JSON 파일은 컨테이너 휘발성이라, 보고서 작성을 위해 결과를
    # 라인 단위 JSONL로 로그에 방출한다. 각 결과 = 개별 print(로그 라인 256KB 제한 회피).
    # rag_response는 1200자로 트림(보고서 충분, 로그 안전).
    if os.environ.get("EVAL_EMIT_JSONL", "1") == "1":
        print("===EVAL_SUMMARY_JSON_BEGIN===", flush=True)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        print("===EVAL_SUMMARY_JSON_END===", flush=True)
        print("===EVAL_RESULTS_JSONL_BEGIN===", flush=True)
        for r in results:
            viols = []
            for v in (r.get("compliance_violations") or [])[:5]:
                if isinstance(v, dict):
                    viols.append(v.get("type") or v.get("description") or str(v))
                else:
                    viols.append(str(v))
            line = {
                "id": r.get("id"),
                "category": r.get("category"),
                "cg": r.get("compliance_grade"),
                "cs": r.get("compliance_score"),
                "qg": r.get("consultation_grade"),
                "qs": r.get("consultation_score"),
                "chk": r.get("checklist_grade"),
                "both_A": r.get("both_A"),
                "ev": r.get("evidence_quality"),
                "ms": r.get("latency_ms"),
                "prompt": (r.get("prompt") or "")[:160],
                "resp": (r.get("rag_response") or "")[:1200],
                "viol": viols,
                "err": r.get("error"),
            }
            print("EVAL_ROW " + json.dumps(line, ensure_ascii=False), flush=True)
        print("===EVAL_RESULTS_JSONL_END===", flush=True)

    # ── 콘솔 요약 출력 ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RAG 배치 평가 결과 요약")
    print("=" * 60)
    print(f"  평가 완료:       {completed}/{total}개")
    print(f"  both_A (목표):   {len(both_A_list)}개  ({summary['both_A_rate_pct']}%)")
    print(f"  에러:            {len(error_list)}개")
    print(f"  평균 응답 시간:  {avg_latency}ms")
    print()
    print("  [컴플라이언스 등급 분포]")
    for g in ("A", "B", "C", "D", "F", "?"):
        cnt = comp_dist.get(g, 0)
        if cnt:
            print(f"    {g}: {cnt}개")
    print()
    print("  [문진 등급 분포]")
    for g in ("A", "B", "C", "D", "F", "?"):
        cnt = cons_dist.get(g, 0)
        if cnt:
            print(f"    {g}: {cnt}개")
    print()
    print(f"  [A 미만 항목: {len(below_A_list)}개]")
    for item in below_A_list[:20]:
        print(
            f"    [{item['id']}] {item['category']} | "
            f"컴={item['compliance_grade']} 문진={item['consultation_grade']} | "
            f"{item['prompt_preview']}..."
        )
    if len(below_A_list) > 20:
        print(f"    ... 외 {len(below_A_list) - 20}개 (전체 결과는 JSON 파일 참조)")
    print()
    print(f"  결과 파일: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()

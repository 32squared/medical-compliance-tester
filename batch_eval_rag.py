"""
RAG 배치 평가기 — 1100개 시나리오를 RAG 응답 + 컴플라이언스/문진 평가.
RAG 생성은 RAG_SERVICE_URL 의 /api/rag/chat HTTP SSE 엔드포인트를 경유한다.
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
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

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

# ── RAG HTTP 클라이언트 설정 ─────────────────────────────────────────────────
_RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "").rstrip("/")
_RAG_TRUST = os.environ.get("RAG_TRUST_SECRET", "")
_RAG_TIMEOUT = int(os.environ.get("RAG_REQUEST_TIMEOUT", "900"))

# ── proxy_server 평가 함수 import ────────────────────────────────────────────
try:
    import proxy_server as _ps
    _evaluate_gpt = _ps._evaluate_gpt
    _evaluate_consultation = _ps._evaluate_consultation
    _evaluate_consultation_checklist = _ps._evaluate_consultation_checklist
    # C-1b: proxy_server의 ID 토큰 취득 함수 재사용(중복 구현 방지)
    _get_rag_id_token = _ps._get_rag_id_token
    logger.info("proxy_server 평가 함수 import 성공")
except Exception as _e:
    logger.error("proxy_server import 실패: %s", _e)
    sys.exit(1)

# ── RAG Cloud Run IAM 인증 (C-1b) ────────────────────────────────────────────
# RAG_ID_TOKEN: 로컬/수동 토큰 주입용 (gcloud auth print-identity-token 결과).
#               Cloud Run Job 환경에서는 미설정 → _get_rag_id_token() 자동 취득.
_RAG_ID_TOKEN_STATIC = os.environ.get("RAG_ID_TOKEN", "").strip()

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

# ── RAG 트랙 전용 문진 평가기 (라이브 _evaluate_consultation 무영향) ──
# 안전우선 4단 구조(정보 선행 후 질문)를 정상 인정. RAG_CONSULT_EVAL=0이면 라이브 폴백.
_USE_RAG_CONSULT = os.environ.get("RAG_CONSULT_EVAL", "1") == "1"
try:
    import rag_consultation_eval as _rce
    _evaluate_consult_rag = _rce.evaluate_consultation_rag
    logger.info("rag_consultation_eval import 성공 (RAG_CONSULT_EVAL=%s)", _USE_RAG_CONSULT)
except Exception as _e:
    logger.warning("rag_consultation_eval import 실패: %s — _evaluate_consultation 폴백", _e)
    _evaluate_consult_rag = None

# ── v3 판정기(medical-eval) 어댑터 — 병존(shadow) ─────────────────────────────
# EVAL_V3=1 일 때만 돈다. v2 결과(compliance/consultation/checklist)에는 손대지 않고
# `eval_v3` 키를 **추가**할 뿐이다(계약 §6.3).
try:
    import eval_v3 as _v3
    _V3_OK, _V3_WHY = _v3.available()
    if _v3.ENABLED and not _V3_OK:
        logger.warning("EVAL_V3=1 이지만 v3 판정기를 쓸 수 없습니다: %s", _V3_WHY)
    elif _v3.ENABLED:
        logger.info("v3 병존 판정 활성 | %s", _v3.versions())
except Exception as _e:
    logger.warning("eval_v3 import 실패 — v3 병존 판정 없이 진행: %s", _e)
    _v3, _V3_OK = None, False


# ── 상수 ─────────────────────────────────────────────────────────────────────
_GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
_SCENARIOS_JSON = os.path.join(_DIR, "scenarios.json")


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 로딩
# ─────────────────────────────────────────────────────────────────────────────

def _scenario_row(s: dict) -> dict:
    """시나리오 1행 → 배치 내부 형식.

    `phrCaseId`·`branch`·`symptomKey` 는 v3 판정용 열이다(REQ-0007). 열이 생기기 전에 적재된
    행은 같은 값이 `tags` 에 `case:<id>` · `branch:<분기>` · `symptom:<증상군>` 으로 들어 있어
    거기서 회수한다.

    `symptomKey` 가 증상 모드(SV) 의 정식 경로다. 이것을 주지 않으면 판정기가 질문 문장에서
    증상군을 추측하는데, 어느 증상이 주소(主訴)인지는 낱말만으로 갈리지 않아 절반 가까이
    못 고르거나 틀린다(증상 골든 50건 측정). 시나리오에 달아 두는 편이 훨씬 정확하다.
    """
    tags = s.get("tags") or []
    tagged = {}
    for t in tags:
        if isinstance(t, str) and ":" in t:
            k, _, v = t.partition(":")
            tagged.setdefault(k, v)
    return {
        "id":                s.get("id", ""),
        "category":          s.get("category", ""),
        "prompt":            s.get("prompt", ""),
        "expected_behavior": s.get("expectedBehavior", ""),
        "should_refuse":     bool(s.get("shouldRefuse", False)),
        "risk_level":        s.get("riskLevel", "MEDIUM"),
        "phr_case_id":       s.get("phrCaseId") or tagged.get("case") or None,
        "branch":            s.get("branch") or tagged.get("branch") or "",
        "symptom_key":       s.get("symptomKey") or tagged.get("symptom") or "",
        "rubric":            s.get("rubric") or [],
    }


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
                scenarios.append(_scenario_row(s))
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
                scenarios.append(_scenario_row(s))
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

def run_rag(query: str, phr_transmit: str = None) -> dict:
    """
    RAG_SERVICE_URL /api/rag/chat SSE 호출 → 응답 텍스트 + evidence_quality + citations 수집.

    `phr_transmit` 을 주면 개인화(기록 모드)로 호출한다 — 최상위 `phr` 축약 필드(transmit
    원문 JSON 문자열)와 `personal_consent: true` 게이트를 함께 보낸다.

    Returns:
        {
            'text': str,
            'evidence_quality': str,   # 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT'
            'citations': list,
            'prompt_version': str or None,     # STOP 메타 — 프롬프트 버전(v17/v18 비교용)
            'personal_injected': list or None, # STOP 메타 — 주입된 개인화 밴드.
                                               #   None=모름, []=미주입(기록 모드 채점 불가)
            'latency_ms': int,
            'error': str or None,
        }
    """
    conv_id = f"batch_eval_{uuid.uuid4().hex[:12]}"
    url = f"{_RAG_SERVICE_URL}/api/rag/chat"
    body = {
        "query": query,
        "conversation_id": conv_id,
        "top_k": 5,
        "enable_guardrails": True,
    }
    if phr_transmit:
        body["phr"] = phr_transmit            # 축약 경로(정식 agent_input_field_to_value 와 겹치면 우선)
        body["personal_consent"] = True       # 방향2 PERSONAL_RAW_TO_LLM 게이트
    payload = json.dumps(body).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-User-Id": "batch-eval",
        "X-User-Name": "batch-eval",
        "X-User-Role": "admin",
    }
    if _RAG_TRUST:
        headers["X-Rag-Trust"] = _RAG_TRUST
    # Cloud Run IAM ID 토큰 주입 (C-1b): --no-allow-unauthenticated 대응.
    # 우선순위: (1) RAG_ID_TOKEN env(수동 주입) > (2) metadata 자동 취득 > (3) 생략.
    _id_token = _RAG_ID_TOKEN_STATIC or _get_rag_id_token()
    if _id_token:
        headers["Authorization"] = "Bearer " + _id_token

    start = time.time()
    text_parts: list = []
    evidence_quality = "UNKNOWN"
    citations: list = []
    prompt_version = None
    personal_injected = None                  # None 과 [] 는 다르다 — 모름 vs 미주입
    error_msg = None

    try:
        req = Request(url, data=payload, headers=headers, method="POST")
        with urlopen(req, timeout=_RAG_TIMEOUT) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\r\n") if isinstance(raw_line, bytes) else raw_line.rstrip("\r\n")
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    event = json.loads(data_str)
                except Exception:
                    continue
                etype = event.get("type", "")
                if etype == "GENERATION":
                    text_parts.append(event.get("text", ""))
                elif etype == "STOP":
                    stop_text = event.get("text", "")
                    if stop_text:
                        text_parts = [stop_text]
                    citations = event.get("citations", [])
                    # STOP 메타(계약 §6.2). meta 안 또는 최상위 — 양쪽 다 받는다.
                    meta = event.get("meta") or {}
                    pv = meta.get("prompt_version", event.get("prompt_version"))
                    if pv:
                        prompt_version = pv
                    pi = meta.get("personal_injected", event.get("personal_injected"))
                    if isinstance(pi, list):
                        personal_injected = pi
                elif etype == "EVIDENCE_CHECK":
                    evidence_quality = event.get("data", {}).get("quality", "UNKNOWN")
                elif etype == "ERROR":
                    error_msg = event.get("message", "RAG 오류")
                    break
    except HTTPError as e:
        body = ""
        try:
            body = e.read(200).decode("utf-8", errors="replace")
        except Exception:
            pass
        if e.code == 403:
            error_msg = (
                f"RAG HTTP 403 (IAM 인증 거부): {body} — "
                "IAM 강제 시 RAG_ID_TOKEN env 또는 Cloud Run Job SA invoker 권한 필요"
            )
        else:
            error_msg = f"RAG HTTP {e.code}: {body}"
    except URLError as e:
        error_msg = f"RAG 연결 실패: {e.reason}"
    except Exception as e:
        error_msg = str(e)

    latency_ms = int((time.time() - start) * 1000)
    return {
        "text": "".join(text_parts),
        "evidence_quality": evidence_quality,
        "citations": citations,
        "prompt_version": prompt_version,
        "personal_injected": personal_injected,
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
        "prompt_version": None,
        "personal_injected": None,
        "eval_v3": None,            # v3 병존 판정(EVAL_V3=1 일 때만). v2 값에는 영향 없음
        "latency_ms": 0,
        "error": None,
    }

    t0 = time.time()

    try:
        # ── 1. RAG 응답 생성 ──────────────────────────────────────
        # 시나리오에 PHR 케이스가 걸려 있으면 개인화(기록 모드)로 호출한다.
        phr_transmit = None                        # RAG 주입용 transmit 원문
        case_id = scenario.get("phr_case_id")
        if case_id and _v3 is not None:
            try:
                phr_transmit, _ = _v3.phr_for(case_id)   # 판정용 phr_cases 는 evaluate_scenario 가 읽는다
                if not phr_transmit:
                    logger.debug("[%s] PHR 케이스 %s transmit 원문 없음 — 증상 모드로 진행", sid, case_id)
            except Exception as e:
                logger.warning("[%s] PHR 케이스 조회 실패(%s): %s", sid, case_id, e)

        rag = run_rag(prompt, phr_transmit=phr_transmit)
        result["rag_response"] = rag["text"]
        result["evidence_quality"] = rag["evidence_quality"]
        result["prompt_version"] = rag.get("prompt_version")
        result["personal_injected"] = rag.get("personal_injected")
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
        # RAG 트랙: rag_consultation_eval(분리 기준) 우선, 없거나 비활성 시 라이브 폴백.
        cons = None
        _use_rag_consult_fn = _USE_RAG_CONSULT and _evaluate_consult_rag
        _consult_fn = _evaluate_consult_rag if _use_rag_consult_fn else _evaluate_consultation
        if _consult_fn and openai_key:
            try:
                if _use_rag_consult_fn:
                    # rag_consultation_eval: log_fn 파라미터 없음
                    cons = _consult_fn(prompt, response_text, openai_key, model=model)
                else:
                    # 호스트 _evaluate_consultation: log_fn 주입으로 monkey-patch 없이 동작
                    cons = _consult_fn(prompt, response_text, openai_key, model=model, log_fn=logger.debug)
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

        # ── 6. v3 병존 판정 (EVAL_V3=1) ───────────────────────────
        # v2 결과는 위에서 이미 확정됐다. 여기서는 `eval_v3` 키만 더한다 — 실패해도
        # 배치는 v2 결과로 그대로 끝난다(3단계 교차표까지는 v3 가 판정을 좌우하지 않는다).
        if _v3 is not None and _v3.ENABLED and _V3_OK:
            rag_meta = {"prompt_version": rag.get("prompt_version") or "unknown",
                        "evidence_quality": rag["evidence_quality"]}
            if rag.get("personal_injected") is not None:
                rag_meta["personal_injected"] = rag["personal_injected"]
                rag_meta["personal_injected_count"] = len(rag["personal_injected"])
            try:
                # 시나리오 → 판정기 인자 매핑은 eval_v3.evaluate_scenario 한 곳뿐이다.
                # 경로마다 따로 매핑하면 한쪽만 고쳐져 두 배치가 다른 판정을 내게 된다.
                result["eval_v3"] = _v3.evaluate_scenario(
                    scenario, prompt, response_text,
                    api_key=openai_key, rag_meta=rag_meta,
                )
            except Exception as e:                 # 어댑터가 이미 잡지만 배치는 절대 멈추지 않는다
                logger.warning("[%s] v3 판정 실패: %s", sid, e)
                result["eval_v3"] = {"error": f"{type(e).__name__}: {e}"}

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
    parser.add_argument(
        "--eval-v3", action="store_true",
        help="v3(온톨로지) 판정을 병존 실행한다 — env EVAL_V3=1 과 같다. v2 결과는 그대로 둔다"
    )
    args = parser.parse_args()

    if args.eval_v3 and _v3 is not None:
        _v3.ENABLED = True
        ok, why = _v3.available()
        if not ok:
            logger.error("--eval-v3 지만 v3 판정기를 쓸 수 없습니다: %s", why)
            sys.exit(1)
        logger.info("v3 병존 판정 활성 | %s", _v3.versions())

    # RAG_SERVICE_URL 필수 체크
    if not _RAG_SERVICE_URL:
        logger.error(
            "RAG_SERVICE_URL 환경변수가 설정되지 않았습니다. "
            "dev: python rag_server.py --port 9100 기동 후 "
            "$env:RAG_SERVICE_URL='http://localhost:9100' 로 주입하세요. 종료."
        )
        sys.exit(1)

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

    # v3 병존 판정이 돌았으면 요약에 버전·분포를 남긴다(교차표의 입력이 된다).
    if any(r.get("eval_v3") for r in results):
        v3_rows = [r["eval_v3"] for r in results if r.get("eval_v3")]
        ok_rows = [v for v in v3_rows if not v.get("error")]
        verdict_dist, gate_dist = {}, {}
        for v in ok_rows:
            verdict_dist[v.get("verdict") or "?"] = verdict_dist.get(v.get("verdict") or "?", 0) + 1
            gate_dist[v.get("legal_verdict") or "?"] = gate_dist.get(v.get("legal_verdict") or "?", 0) + 1
        first = ok_rows[0] if ok_rows else {}
        summary["eval_v3"] = {
            "scored": len(ok_rows),
            "error_count": len(v3_rows) - len(ok_rows),
            "verdict_dist": verdict_dist,
            "legal_verdict_dist": gate_dist,
            "eval_version": first.get("eval_version"),
            "ontology_version": first.get("ontology_version"),
            "judge_model": first.get("judge_model"),
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
                "pv_ver": r.get("prompt_version"),
            }
            v3 = r.get("eval_v3")
            if v3:
                # 등급 열은 두 개로 둔다 — 합치면 어느 축이 떨어졌는지 사라진다(계약 §7).
                line["v3"] = {
                    "verdict": v3.get("verdict"), "legal": v3.get("legal_verdict"),
                    "hits": v3.get("legal_hits"), "axis": v3.get("validity_axis"),
                    "vgrade": v3.get("validity_grade"), "unmet": v3.get("validity_unmet"),
                    "ugrade": v3.get("uv_grade"), "cap": v3.get("grade_cap"),
                    "err": v3.get("error"),
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
    if summary.get("eval_v3"):
        v3s = summary["eval_v3"]
        print()
        print(f"  [v3 병존 판정 — {v3s.get('eval_version')} / 온톨로지 {v3s.get('ontology_version')}]")
        print(f"    판정 {v3s['scored']}건, 실패 {v3s['error_count']}건")
        print(f"    게이트: " + ", ".join(f"{k} {v}개" for k, v in sorted(v3s["legal_verdict_dist"].items())))
        print(f"    최종:   " + ", ".join(f"{k} {v}개" for k, v in sorted(v3s["verdict_dist"].items())))
    print()
    print(f"  결과 파일: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()

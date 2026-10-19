# -*- coding: utf-8 -*-
"""
eval_v3.py — medical-eval(온톨로지 기반 v3 판정기) 호스트 어댑터
================================================================
호스트가 v3 판정기에 대해 아는 것은 이 파일 하나다. 배치·서버는 `medical_eval` 을
직접 import 하지 않는다(scripts/check_no_cross_import.py --forbid eval 로 강제).

경계 (packages/medical_eval/CLAUDE.md '경계'):
  - medical-eval 은 라이브러리다. HTTP·DB·UI·배치 실행은 전부 호스트 몫이다.
  - 판정 진입점은 `evaluate` / `evaluate_batch` 둘뿐이다.

병존(shadow) 운영:
  EVAL_V3=1 일 때만 판정한다. 기본값은 0 — 기존 배치의 비용·동작을 건드리지 않는다.
  v3 결과는 기존 compliance/consultation 결과 옆에 `eval_v3` 키로 **추가**될 뿐,
  both_A 등 기존 판정에는 영향을 주지 않는다(3단계 교차표 → 4단계 라이브 순서).

저장 형태:
  `compact()` 가 등급·규칙 id·버전과 **걸린 문장**(규칙·항목별 문장 번호 + 인용문 QUOTE_MAX 자)을 남긴다.
  claims 전체(삼중항·레벨·출처)와 PHR 기록 값은 남기지 않는다 — medical-eval 데이터 규칙(케이스 출처
  미확인)이 막는 것은 기록 원문이고, 답변 문장은 결과 옆에 통째로 저장되는 답변의 일부다(2026-10-19).
"""
import os
import sys
import logging
import threading

logger = logging.getLogger("eval_v3")

_DIR = os.path.dirname(os.path.abspath(__file__))
#: 판정기 패키지 위치. EVAL_V3_PKG 로 바꾸면 병합 전 판정기 후보(예: packages/medical_eval_candidate)를
#: 그 실행에만 쓸 수 있다 — 재판정 잡이 운영 배치의 판정기를 바꾸지 않고 후보를 시험하는 용도.
_PKG = (os.environ.get("EVAL_V3_PKG", "").strip()
        or os.path.join(_DIR, "packages", "medical_eval"))
_SRC = os.path.join(_PKG, "src")
_SNAPSHOT_DIR = os.path.join(_PKG, "ontology", "snapshot")

#: 병존 판정 스위치. 1 이어야 v3 가 돈다(기본 꺼짐).
ENABLED = os.environ.get("EVAL_V3", "0") == "1"
#: 판정 모델. 미지정 시 medical_eval.DEFAULT_MODEL.
MODEL = os.environ.get("EVAL_V3_MODEL", "").strip() or None
#: [구형, 기본 꺼짐] 1차 판정 모델이 legal fail 을 내면 이 모델로 같은 답변을 **통째로** 한 번 더 판정하고 2차 결과로
#: 1차를 대체하던 2단 판정(2026-09-18 mini→gpt-5.4, 10-14 luna→sol). 1차 근거가 2차에 전달되지 않아 두 모델이 서로
#: 다른 규칙으로 FAIL 시키는 비일관을 남겼고(Dev 10/16 25건 중 6건, DOC-HSCEY), 판정기 context-v1(1차 후보 → 2차 문맥
#: 판정 뒤 확정)이 같은 역할을 라이브러리 안에서 하므로 2026-10-19 폐지(medical-eval 설계 context_v1.md §4.1).
#: 재현·비교용으로만 `EVAL_V3_ESCALATE=1` 과 함께 켠다. 모델만 지정하고 스위치가 없으면 돌지 않는다.
ESCALATE_MODEL = os.environ.get("EVAL_V3_ESCALATE_MODEL", "").strip() or None
ESCALATE_ENABLED = os.environ.get("EVAL_V3_ESCALATE", "0") == "1"
#: 판정기가 `legal.status == "needs_rejudge"` 를 돌려주면(2차 문맥 판정이 키 없음·타임아웃·형식 오류로 실패해
#: 후보가 review 로 남은 상태 — 2026-10-19 사용자 결정 ①) 같은 모델·같은 입력으로 캐시 없이 다시 판정한다.
#: 최대 횟수. 0 이면 재판정하지 않고 needs_rejudge 를 그대로 저장한다.
REJUDGE_MAX = int(os.environ.get("EVAL_V3_REJUDGE_MAX", "2") or 0)
#: 판정기가 쓰는 상태값. 라이브러리 연동 규격 v0.5.20(예정)과 같아야 한다.
NEEDS_REJUDGE = "needs_rejudge"
#: gpt-6 계열 reasoning_effort. 1차는 EVAL_V3_REASONING_EFFORT(판정기 judge_client 도 같은 변수를 기본값으로
#: 읽는다), 2차는 EVAL_V3_ESCALATE_REASONING_EFFORT. 값은 검증 없이 그대로 보낸다 — 허용값은 모델별로 다르다
#: (gpt-6-luna none/low/medium/high · gpt-6-sol low/medium/high). 운영(2026-10-14): 1차 gpt-6-luna none · 2차 gpt-6-sol low.
REASONING_EFFORT = os.environ.get("EVAL_V3_REASONING_EFFORT", "").strip() or None


def _escalate_reasoning_effort(first, env_value):
    """2차 effort. 지정이 없으면 1차 값을 따르되 `none` 은 gpt-6-luna 만 받으므로 2차에는 `low` 로 바꾼다."""
    v = (env_value or "").strip()
    if v:
        return v
    return "low" if first == "none" else first


ESCALATE_REASONING_EFFORT = _escalate_reasoning_effort(
    REASONING_EFFORT, os.environ.get("EVAL_V3_ESCALATE_REASONING_EFFORT"))
#: 스냅샷 경로 고정용(미지정 시 ontology/snapshot 최신 버전).
SNAPSHOT_PATH = os.environ.get("EVAL_V3_SNAPSHOT", "").strip() or None

#: SV 축(증상 상담)이 쓰는 42 증상군 체크리스트.
#: medical_eval 저장소에도 같은 파일(data/ref)이 있지만, 배포 업로드 규칙(.gcloudignore 의
#: `data/`)이 그 디렉터리를 통째로 제외하므로 컨테이너 안에는 없을 수 있다. 없으면 SV-02·03·
#: 04·06 이 조용히 `na` 가 되어 판정이 속 빈 채로 돈다. 호스트가 반드시 싣는 공유 번들
#: (medical_shared, 두 파일은 동일)을 기본 경로로 박아 그 경로 의존을 끊는다.
CHECKLIST_ENV = "MEDICAL_EVAL_CHECKLISTS"
_SHARED_CHECKLISTS = os.path.join(
    _DIR, "packages", "medical_shared", "compliance_rules", "consultation_checklists.json")


def _ensure_checklists_env() -> str:
    """체크리스트 경로를 환경변수로 고정하고 그 경로를 돌려준다(없으면 빈 문자열)."""
    given = os.environ.get(CHECKLIST_ENV, "").strip()
    if given:
        return given if os.path.isfile(given) else ""
    for candidate in (_SHARED_CHECKLISTS,
                      os.path.join(_PKG, "data", "ref", "consultation_checklists.json")):
        if os.path.isfile(candidate):
            os.environ[CHECKLIST_ENV] = candidate
            return candidate
    return ""

_lock = threading.Lock()
_snapshot = None
_unavailable_reason = None


# ─────────────────────────────────────────────────────────────────────────────
# 가용성
# ─────────────────────────────────────────────────────────────────────────────

def _import_medical_eval():
    """서브모듈이 없으면 ImportError. 호스트는 이 예외를 잡아 v3 없이 계속 돈다."""
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
    import medical_eval  # noqa: F401  (packages/medical_eval/src/medical_eval)
    return medical_eval


def available() -> tuple:
    """(가능 여부, 사유). 서브모듈 미초기화(`git submodule update --init`)면 False."""
    global _unavailable_reason
    if not os.path.isdir(_SRC):
        _unavailable_reason = (
            "packages/medical_eval 서브모듈이 없습니다 — git submodule update --init --recursive"
        )
        return False, _unavailable_reason
    try:
        _import_medical_eval()
    except Exception as e:
        _unavailable_reason = f"medical_eval import 실패: {e}"
        return False, _unavailable_reason
    _ensure_checklists_env()
    return True, ""


def get_snapshot():
    """온톨로지 스냅샷 1회 로드 후 캐시. 배치 전체가 같은 스냅샷을 쓴다."""
    global _snapshot
    if _snapshot is not None:
        return _snapshot
    with _lock:
        if _snapshot is not None:
            return _snapshot
        _import_medical_eval()
        from medical_eval.ontology import latest_snapshot_path, load_snapshot
        path = SNAPSHOT_PATH or latest_snapshot_path(_SNAPSHOT_DIR)
        if not path:
            raise FileNotFoundError(f"온톨로지 스냅샷이 없습니다: {_SNAPSHOT_DIR}")
        _snapshot = load_snapshot(path)
        logger.info("온톨로지 스냅샷 로드: %s (%s)", os.path.basename(str(path)), _snapshot.version)
    return _snapshot


def versions() -> dict:
    """리포트 머리말용 — 판정기·온톨로지·모델 버전. 사용 불가면 available 사유를 담는다."""
    ok, why = available()
    if not ok:
        return {"available": False, "reason": why}
    import medical_eval as me
    out = {"available": True, "eval_version": me.EVAL_VERSION,
           "judge_model": MODEL or me.DEFAULT_MODEL, "enabled": ENABLED}
    out["checklists"] = bool(_ensure_checklists_env())
    try:
        out["ontology_version"] = get_snapshot().version
    except Exception as e:
        out["ontology_version"] = None
        out["reason"] = str(e)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 판정
# ─────────────────────────────────────────────────────────────────────────────

def _rule_ids(hits) -> list:
    return sorted({h.get("rule_id") for h in (hits or []) if h.get("rule_id")})


QUOTE_MAX = 240
_EV_KEYS = ("basis", "phrase_id", "id", "kind", "rule_id", "status", "text", "phrase", "example_code", "example_kind",
            "same_as_nearest", "person_attributed", "attrib_source", "attrib_level", "rationale", "department")


def evidence_rows(evidence, limit=6):
    """판정 근거 목록을 저장용으로 줄인다(키 고정, 문자열 160자, 최대 limit 개)."""
    out = []
    for e in (evidence or [])[:limit]:
        if not isinstance(e, dict):
            continue
        row = {}
        for k in _EV_KEYS:
            v = e.get(k)
            if v is None or v == "" or v == []:
                continue
            row[k] = v[:160] if isinstance(v, str) else v
        if row:
            out.append(row)
    return out


def _claim_maps(claims):
    """claims → ({주장 번호: 원문 문장 번호}, {번호: 문장 글자}).

    쪼갠 주장(claims-v4 part 1·2)은 text 가 문장 전체이고 source_idx 가 원래 문장 번호다. 쪼개지 않은
    주장은 idx == source_idx. 그래서 번호 n 의 글자는 idx == n 인 주장의 text 로 늘 찾을 수 있다
    (UV 항목은 문장 번호, PV·SV·게이트는 주장 번호를 쓰는데 두 경우 모두 맞는다)."""
    sentence_of, text_of = {}, {}
    for pos, c in enumerate(claims or [], 1):
        if not isinstance(c, dict):
            continue
        try:
            idx = int(c.get("idx") or pos)
        except (TypeError, ValueError):
            idx = pos
        try:
            sent = int(c.get("source_idx") or idx)
        except (TypeError, ValueError):
            sent = idx
        sentence_of[idx] = sent
        text = c.get("text")
        if isinstance(text, str) and text.strip():
            text_of.setdefault(idx, text.strip())
            text_of.setdefault(sent, text.strip())
    return sentence_of, text_of


def _to_sentence(n, sentence_of):
    try:
        return sentence_of.get(int(n), int(n))
    except (TypeError, ValueError):
        return n


def compact(result: dict) -> dict:
    """전체 결과 → 호스트가 저장·집계하는 최소 형태.

    claims 전체(삼중항·레벨·출처)는 남기지 않는다. 다만 판정이 **걸린 문장**은 규칙·항목마다 번호와 글자
    (quote, QUOTE_MAX 자)로 남긴다 — 어떤 구문이 어떤 기준으로 판정됐는지 답변 원문을 따로 열지 않고
    읽을 수 있게 하기 위해서다(2026-10-19 결정). 문장은 이미 함께 저장되는 답변의 일부라 새 데이터가 아니다.
    """
    if not result:
        return {}
    legal = result.get("legal") or {}
    validity = result.get("validity") or {}
    uv = result.get("uv") or {}
    sentence_of, text_of = _claim_maps(result.get("claims"))
    # v3.1(판정기 f3c9723+)부터 PHR 은 grade=null 이고 v3.0 등급은 grade_legacy 로 1 릴리스 병기된다.
    # 등급 없음이 PASS 로 읽히지 않게(verdict_of 기본값) grade_legacy 로 이어 쓴다.
    grade = validity.get("grade") or validity.get("grade_legacy")
    basis = validity.get("grade_basis") or validity.get("grade_legacy_basis") or {}
    answer = validity.get("answer") if isinstance(validity.get("answer"), dict) else {}
    out = {
        "verdict": result.get("verdict"),
        "mode": result.get("mode"),
        "legal_verdict": legal.get("verdict"),
        "legal_hits": _rule_ids(legal.get("hits")),
        "legal_review_hits": _rule_ids(legal.get("review_hits")),
        "legal_cap_hits": _rule_ids(legal.get("cap_hits")),
        "validity_axis": validity.get("axis"),
        "validity_grade": grade,
        "validity_grade_source": ("legacy" if grade and not validity.get("grade") else None),
        "validity_status": validity.get("status"),
        "validity_unmet": list(basis.get("unmet_ids") or []),
        "grade_cap": list(basis.get("cap") or []),
        "uv_grade": uv.get("grade"),
        "uv_status": uv.get("status"),
        "uv_unmet": list(((uv.get("grade_basis") or {}).get("unmet_ids")) or []),
        "summary_line": result.get("summary_line"),
        "eval_version": result.get("eval_version"),
        "ontology_version": result.get("ontology_version"),
        "prompt_version": result.get("prompt_version"),
        "judge_model": result.get("judge_model"),
        "gate_mode": result.get("gate_mode"),
        # 연동 규격 v0.5.19(2026-10-07) — 게이트·유효성 로직 버전을 결과와 함께 남긴다. 번호가 바뀌면
        # LG·PV 기준선이 무효라 비교 때 판별 기준이 된다. legal.v6a(LLM 2차 스위치 블록)는 저장하지 않는다.
        "legal_version": legal.get("version"),
        "validity_version": validity.get("version"),
    }
    # 연동 규격 v0.5.20(예정, context-v1): legal.status 는 2차 문맥 판정이 끝났는지(ok / needs_rejudge),
    # legal.context 는 후보·판정 수와 프롬프트 판. 재판정 경로와 집계가 읽는다. 없으면(구판 판정기) 넣지 않는다.
    if legal.get("status") is not None:
        out["legal_status"] = legal.get("status")
    ctx = legal.get("context")
    if isinstance(ctx, dict):
        out["legal_context"] = {k: ctx.get(k) for k in ("prompt_version", "candidates", "judged")
                                if ctx.get(k) is not None}
    if answer:                                         # v3.1 PHR [3b] 정답·허용답 — met/unmet
        out["validity_answer"] = answer.get("result")
        out["validity_answer_status"] = answer.get("status")
    checklist = validity.get("checklist")
    if checklist:                                      # 증상 모드(SV) — red flag 커버리지·LG-16
        out["checklist"] = checklist

    # ── 상세(호스트 DB 저장용, 계약 §3.8 B5 집계 재료) ──
    def _hit_rows(hits):
        rows = []
        for h in (hits or []):
            if not isinstance(h, dict):
                continue
            ci = h.get("claim_idx")
            row = {"rule_id": h.get("rule_id"), "severity": h.get("severity"),
                   "level": h.get("level"), "claim_idx": ci,
                   "status": h.get("status")}
            if ci is not None:
                row["sentence_idx"] = _to_sentence(ci, sentence_of)
            # 판정 근거(2026-09-22 계획 0단계): 걸린 문장·검출기·사전·귀속 이유를 남겨 사람이
            # 답변 원문을 따로 열지 않고 검토할 수 있게 한다. 문장은 답변의 일부라 새 데이터가 아니다.
            quote = h.get("quote") or (text_of.get(ci) if ci is not None else None)
            if quote:
                row["quote"] = str(quote)[:QUOTE_MAX]
            for k in ("detectors", "decision", "review"):
                if h.get(k):
                    row[k] = h[k]
            ev = evidence_rows(h.get("evidence"))
            if ev:
                row["evidence"] = ev
            rows.append(row)
        return rows

    def _item_rows(items, *, already_sentence=False):
        """PV·SV 항목의 claim_idx 는 주장 번호, UV 항목은 이미 문장 번호다(aggregate._unmet_lines 와 같은 규칙).
        문장 번호와 그 문장 글자(최대 3개)를 함께 남겨 미충족 사유가 가리키는 구문을 바로 읽게 한다."""
        rows = []
        for it in (items or []):
            if not isinstance(it, dict) or not it.get("id"):
                continue
            row = {"id": it.get("id"), "result": it.get("result"), "detail": it.get("detail")}
            where = it.get("claim_idx")
            if isinstance(where, (list, tuple)) and where:
                row["claim_idx"] = list(where)
                sents = []
                for n in where:
                    s = n if already_sentence else _to_sentence(n, sentence_of)
                    if s not in sents:
                        sents.append(s)
                row["sentence_idx"] = sents
                quotes = [str(text_of[n])[:QUOTE_MAX] for n in sents[:3] if n in text_of]
                if quotes:
                    row["quotes"] = quotes
            rows.append(row)
        return rows

    out["legal_hit_detail"] = _hit_rows(legal.get("hits")) + _hit_rows(legal.get("review_hits"))
    out["legal_max_level"] = legal.get("max_level")
    out["validity_items"] = _item_rows(validity.get("items"))
    out["uv_items"] = _item_rows(uv.get("items"), already_sentence=True)
    out["uv_intent"] = uv.get("intent")
    out["uv_prompt_version"] = uv.get("prompt_version")
    slots = uv.get("slots") or {}
    out["uv_slots"] = {k: bool((v or {}).get("present")) for k, v in slots.items()
                       if isinstance(v, dict)}
    fc = validity.get("fact_check") or {}
    if fc:
        out["fact_check"] = {k: fc.get(k) for k in
                             ("status", "cited", "matched", "fabricated", "stale_meds",
                              "oldest_record_months") if k in fc}
    claims = result.get("claims") or []
    levels = {}
    fallback = 0
    for c in claims:
        if not isinstance(c, dict):
            continue
        lv = c.get("level") or "?"
        levels[lv] = levels.get(lv, 0) + 1
        if c.get("origin") == "fallback":
            fallback += 1
    out["claim_count"] = len(claims)
    out["claim_levels"] = levels
    out["claim_fallback"] = fallback
    rm = result.get("rag_meta") or {}
    if rm:
        out["rag_meta"] = {"prompt_version": rm.get("prompt_version"),
                           "personal_injected_count": rm.get("personal_injected_count"),
                           "scored": rm.get("scored"), "skip_reason": rm.get("skip_reason")}
    if result.get("summary"):
        out["summary"] = result.get("summary")
    return out


def evaluate(question: str, answer: str, *, api_key=None, **kwargs) -> dict:
    """1건 판정 → `compact()` 형태. 판정 실패는 예외 대신 `{'error': ...}` 로 돌려준다.

    kwargs 는 medical_eval.evaluate 의 선택 인자를 그대로 넘긴다
    (`expected_behavior` · `symptom_key` · `prior_turns` · `rubric` · `phr` · `rag_meta` …).
    """
    ok, why = available()
    if not ok:
        return {"error": why}
    model = MODEL
    if not model:                                     # 서브모듈 import 는 필요할 때만(CI 에는 없을 수 있다)
        import medical_eval as me
        model = me.DEFAULT_MODEL
    try:
        result = _judge(question, answer, model, api_key, kwargs, reasoning_effort=REASONING_EFFORT)
    except Exception as e:
        logger.warning("v3 판정 실패: %s", e)
        return {"error": f"{type(e).__name__}: {e}"}
    result, rejudge = _rejudge_if_needed(question, answer, model, api_key, kwargs, result,
                                         reasoning_effort=REASONING_EFFORT)
    escalation = None
    if (ESCALATE_ENABLED and ESCALATE_MODEL and ESCALATE_MODEL != model
            and (result.get("legal") or {}).get("verdict") == "fail"
            and not _needs_rejudge(result)):           # 문맥 판정이 안 끝난 결과는 다른 모델로 덮지 않는다
        first = compact(result)
        try:
            result = _judge(question, answer, ESCALATE_MODEL, api_key, kwargs,
                            reasoning_effort=ESCALATE_REASONING_EFFORT)
            # 2차 모델의 결과도 문맥 판정이 안 끝났으면 같은 재판정 정책을 적용한다(1차와 같은 규칙).
            result, esc_rejudge = _rejudge_if_needed(question, answer, ESCALATE_MODEL, api_key, kwargs, result,
                                                     reasoning_effort=ESCALATE_REASONING_EFFORT)
            if esc_rejudge:
                rejudge = dict(esc_rejudge, stage="escalation")
            escalation = {"first_model": model, "first_verdict": first.get("verdict"),
                          "first_hits": first.get("legal_hits"), "model": ESCALATE_MODEL,
                          "verdict": result.get("verdict")}
        except Exception as e:                         # 2차 실패 → 1차 결과를 그대로 쓴다
            logger.warning("v3 2차 판정 실패(%s): %s", ESCALATE_MODEL, e)
            escalation = {"first_model": model, "first_verdict": first.get("verdict"),
                          "first_hits": first.get("legal_hits"), "model": ESCALATE_MODEL,
                          "error": f"{type(e).__name__}: {str(e)[:120]}"}
    out = compact(result)
    if rejudge:
        out["judge_rejudge"] = rejudge
    if escalation:
        out["judge_escalation"] = escalation
    return out


def _needs_rejudge(result: dict) -> bool:
    """판정기가 2차 문맥 판정을 끝내지 못했다고 표시했는가(`legal.status == needs_rejudge`)."""
    return ((result or {}).get("legal") or {}).get("status") == NEEDS_REJUDGE


def _rejudge_if_needed(question, answer, model, api_key, kwargs, result, reasoning_effort=None):
    """`needs_rejudge` 면 같은 모델·같은 입력으로 캐시 없이 최대 REJUDGE_MAX 회 다시 판정한다.

    끝난 결과(status 가 needs_rejudge 가 아님)가 나오면 그것을 쓰고, 횟수를 다 써도 못 끝내면 마지막 결과를
    그대로 둔다 — 판정기가 후보를 review 로 남긴 상태라 verdict 는 보수적으로 바뀌지 않는다(결정 ①: 거짓 FAIL 로
    덮지 않는다). 재판정 호출이 예외를 내면 직전 결과를 유지하고 오류를 기록한다.
    돌려주는 값: (최종 result, judge_rejudge 메타 또는 None). 메타 = {"attempts", "resolved", "errors"}.
    REJUDGE_MAX=0 이면 attempts=0·resolved=False 로 "재판정 정책상 건너뜀" 을 남긴다 — 집계는 attempts>0 만 센다.
    """
    if not _needs_rejudge(result):
        return result, None
    attempts, errors = 0, []
    while _needs_rejudge(result) and attempts < max(REJUDGE_MAX, 0):
        attempts += 1
        retry_kwargs = dict(kwargs, use_cache=False)   # 같은 입력이라 캐시를 타면 같은 실패가 돌아온다
        try:
            nxt = _judge(question, answer, model, api_key, retry_kwargs, reasoning_effort=reasoning_effort)
        except Exception as e:
            logger.warning("v3 재판정(needs_rejudge) %d회차 실패: %s", attempts, e)
            errors.append(f"{type(e).__name__}: {str(e)[:120]}")
            continue
        result = nxt
    resolved = not _needs_rejudge(result)
    if not resolved:
        logger.warning("v3 재판정 %d회 뒤에도 needs_rejudge — review 로 남김", attempts)
    meta = {"attempts": attempts, "resolved": resolved}
    if errors:
        meta["errors"] = errors
    return result, meta


def _judge(question, answer, model, api_key, kwargs, reasoning_effort=None):
    """medical_eval.evaluate 1회 호출(모델 지정). 예외는 호출자가 처리한다.

    `reasoning_effort` 가 있으면 판정기의 기본 호출을 `chat` 콜백으로 바꿔 그 값을 judge_client.chat_json 에
    넘긴다(1차·2차가 다른 effort 를 쓰려면 호출마다 달라야 하므로 환경변수만으로는 안 된다). 호출자가 `chat` 을
    직접 넘겼으면(테스트·재현) 그대로 둔다.
    """
    import medical_eval as me
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    kwargs = dict(kwargs)
    if reasoning_effort and kwargs.get("chat") is None:
        kwargs["chat"] = _chat_with_effort(key, reasoning_effort, kwargs)
    return me.evaluate(
        question or "", answer or "",
        model=model,
        ontology=get_snapshot(),
        api_key=key,
        with_quote=True,                               # 걸린 문장 글자를 hits[].quote 로 받는다(compact 가 QUOTE_MAX 로 자름)
        **kwargs
    )


def _chat_with_effort(api_key, reasoning_effort, kwargs):
    """판정기 서브판정의 기본 chat 과 같은 인자(api_key·timeout·cache_dir·use_cache·stats_out)에
    reasoning_effort 만 더한 콜백. 기본값은 medical_eval.evaluate 와 같게 둔다."""
    from medical_eval.judge_client import DEFAULT_CACHE_DIR
    from medical_eval.judge_client import chat_json as _cj
    timeout = kwargs.get("timeout", 60)
    cache_dir = kwargs.get("cache_dir") or DEFAULT_CACHE_DIR
    use_cache = kwargs.get("use_cache", True)
    stats_out = kwargs.get("stats_out")

    def chat(model_, system_, user_):
        return _cj(model_, system_, user_, api_key=api_key, timeout=timeout,
                   reasoning_effort=reasoning_effort, cache_dir=cache_dir,
                   use_cache=use_cache, stats_out=stats_out)
    return chat


def evaluate_batch(items, *, api_key=None, max_workers=4, on_result=None, **defaults) -> list:
    """여러 건 판정(계약 §6.1). 순서 보존·1건 실패 무중단은 라이브러리가 보장한다."""
    ok, why = available()
    if not ok:
        return [{"item_id": (it or {}).get("item_id"), "error": why} for it in (items or [])]
    import medical_eval as me

    def _wrap(result):
        if on_result is not None:
            on_result(result)

    raw = me.evaluate_batch(
        items,
        model=MODEL or me.DEFAULT_MODEL,
        ontology=get_snapshot(),
        api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
        max_workers=max_workers,
        on_result=_wrap if on_result is not None else None,
        with_quote=True,
        **defaults
    )
    out = []
    for r in raw:
        if r.get("error"):
            out.append({"item_id": r.get("item_id"), "error": r["error"]})
        else:
            row = compact(r)
            row["item_id"] = r.get("item_id")
            row["error"] = None
            out.append(row)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PHR 케이스 (기록 모드)
# ─────────────────────────────────────────────────────────────────────────────
# 형식이 둘이라는 점이 함정이다(계약 §6.2 '주입 포맷 주의').
#   RAG 에 보내는 것  = transmit 원문(JSON 문자열)
#   evaluate() 에 넘기는 것 = phr_cases 형식
# **원본은 transmit 하나**이고, phr_cases 는 medical-eval `scripts/normalize_phr.py` 가
# 그 원본에서 만든다. 호스트는 두 산출물을 읽기만 하고 형식 변환을 하지 않는다 —
# 호스트가 따로 변환하기 시작하면 두 형식이 언젠가 어긋난다.
#
#   PHR_TRANSMIT_PATH — {"<case_id>": {transmit 객체}, ...}  (RAG 주입용)
#   PHR_CASES_PATH    — phr_cases.json: [{"case_id": …, …}, …]  (판정용)
# 둘 다 없으면 기록 모드는 그냥 돌지 않는다(증상 모드로만 판정). 케이스 원문은
# 출처 확인 전까지 저장소에 커밋하지 않으므로 경로는 환경변수로만 받는다.

PHR_TRANSMIT_PATH = os.environ.get("PHR_TRANSMIT_PATH", "").strip()
PHR_CASES_PATH = os.environ.get("PHR_CASES_PATH", "").strip()

_phr_lock = threading.Lock()
_phr_transmit = None
_phr_cases = None


def _load_json(path):
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_phr():
    """두 파일을 1회 읽어 case_id → (transmit, case) 로 색인한다."""
    global _phr_transmit, _phr_cases
    if _phr_transmit is not None:
        return
    with _phr_lock:
        if _phr_transmit is not None:
            return
        transmit, cases = {}, {}
        if PHR_TRANSMIT_PATH:
            try:
                raw = _load_json(PHR_TRANSMIT_PATH)
                transmit = raw if isinstance(raw, dict) else {}
            except Exception as e:
                logger.warning("PHR transmit 로드 실패 (%s): %s", PHR_TRANSMIT_PATH, e)
        if PHR_CASES_PATH:
            try:
                raw = _load_json(PHR_CASES_PATH)
                rows = raw if isinstance(raw, list) else (raw or {}).get("cases", [])
                cases = {c.get("case_id"): c for c in rows if isinstance(c, dict) and c.get("case_id")}
            except Exception as e:
                logger.warning("phr_cases 로드 실패 (%s): %s", PHR_CASES_PATH, e)
        if transmit and cases:
            only_t = sorted(set(transmit) - set(cases))
            only_c = sorted(set(cases) - set(transmit))
            if only_t or only_c:
                # 같은 case_id 가 두 파일에 다 있어야 '같은 기록'이 보장된다(계약 §6.2).
                logger.warning(
                    "PHR 케이스 목록 불일치 — transmit 전용 %s / phr_cases 전용 %s",
                    only_t[:5], only_c[:5],
                )
        _phr_transmit, _phr_cases = transmit, cases
        logger.info("PHR 케이스 로드: transmit %d건 · phr_cases %d건", len(transmit), len(cases))


# ────────────────────────────────────────────────────────────
# 배치 집계 (온톨로지 평가 페이지 /api/eval-v3/runs · job_runner 로그)
# ────────────────────────────────────────────────────────────
VERDICT_ORDER = ["FAIL", "D", "C", "B", "A", "PASS"]


def verdict_of(v3):
    """compact 결과 → 'FAIL' | 'A'~'D' | 'PASS'(등급 없음) | None(없음·오류)."""
    if not v3 or not isinstance(v3, dict) or v3.get("error"):
        return None
    if v3.get("legal_verdict") == "fail":
        return "FAIL"
    return str(v3.get("validity_grade") or "PASS").upper()


def run_summary(results):
    """배치 결과 목록 → v3 집계. id·등급·규칙 id 만 세고 답변 원문은 보지 않는다.

    evalV3 가 하나도 없으면 None — 페이지는 그런 실행을 목록에서 뺀다.
    """
    def _inc(d, k):
        k = k if k not in (None, "") else "-"
        d[k] = d.get(k, 0) + 1

    rows = [r for r in (results or []) if isinstance(r, dict) and r.get("evalV3")]
    if not rows:
        return None
    out = {
        "n": len(rows), "err": 0,
        "gate": {"pass": 0, "fail": 0, "review": 0},
        "verdict": {}, "validity": {}, "uv": {}, "axis": {},
        "rule_hits": {}, "review_hits": {}, "unmet": {}, "uv_unmet": {}, "intent": {},
        "prompt_versions": {}, "categories": {},
        "escalated": 0, "escalated_fail": 0, "final_v3": 0,
        "rejudged": 0, "rejudge_unresolved": 0,
        "judge_model": None, "escalate_model": None,
        "ontology_version": None, "eval_version": None,
    }
    for r in rows:
        v = r.get("evalV3") or {}
        cat = r.get("category") or "-"
        c = out["categories"].setdefault(cat, {"n": 0, "fail": 0, "err": 0})
        c["n"] += 1
        if r.get("finalSource") == "v3":
            out["final_v3"] += 1
        if v.get("error"):
            out["err"] += 1
            c["err"] += 1
            continue
        g = v.get("legal_verdict")
        if g in out["gate"]:
            out["gate"][g] += 1
        vd = verdict_of(v)
        _inc(out["verdict"], vd)
        if vd == "FAIL":
            c["fail"] += 1
        _inc(out["validity"], v.get("validity_grade"))
        _inc(out["uv"], v.get("uv_grade"))
        _inc(out["axis"], v.get("validity_axis"))
        for h in (v.get("legal_hits") or []):
            _inc(out["rule_hits"], h)
        for h in (v.get("legal_review_hits") or []):
            _inc(out["review_hits"], h)
        for u in (v.get("validity_unmet") or []):
            _inc(out["unmet"], u)
        for u in (v.get("uv_unmet") or []):
            _inc(out["uv_unmet"], u)
        _inc(out["intent"], v.get("uv_intent"))
        pv = ((v.get("rag_meta") or {}).get("prompt_version")) or v.get("prompt_version")
        _inc(out["prompt_versions"], pv)
        rj = v.get("judge_rejudge")
        if rj and (rj.get("attempts") or 0) > 0:        # attempts=0(REJUDGE_MAX=0)은 재판정한 것이 아니다
            out["rejudged"] += 1
        if v.get("legal_status") == NEEDS_REJUDGE:      # 재판정 뒤에도 못 끝낸 건(또는 REJUDGE_MAX=0)
            out["rejudge_unresolved"] += 1
        esc = v.get("judge_escalation")
        if esc:
            out["escalated"] += 1
            if esc.get("verdict") == "FAIL":
                out["escalated_fail"] += 1
            if not out["escalate_model"]:
                out["escalate_model"] = esc.get("model")
            if not out["judge_model"]:
                out["judge_model"] = esc.get("first_model")
        if not out["judge_model"]:
            out["judge_model"] = v.get("judge_model")
        if not out["ontology_version"]:
            out["ontology_version"] = v.get("ontology_version")
        if not out["eval_version"]:
            out["eval_version"] = v.get("eval_version")
        if v.get("human_review"):
            out["human_review"] = out.get("human_review", 0) + 1
    return out


# ────────────────────────────────────────────────────────────
# 사람 검토 정정 (POST /api/history/<runId>/review)
# ────────────────────────────────────────────────────────────
#: batch_executor.BatchExecutor.V3_SCORE 와 같은 값이어야 한다(테스트가 확인).
V3_SCORE = {"A": 100, "B": 85, "C": 70, "D": 60}


def final_of(v3):
    """v3 결과 → (finalScore, passed). BatchExecutor._v3_final 과 같은 규칙. 없으면 None."""
    if not v3 or not isinstance(v3, dict) or v3.get("error"):
        return None
    legal = v3.get("legal_verdict")
    if legal not in ("pass", "fail"):
        return None
    if legal == "fail":
        return 0, False
    return V3_SCORE.get(str(v3.get("validity_grade") or "").upper(), 90), True


def apply_human_review(results, reviews, *, by, at):
    """사람 검토로 v3 법률 판정을 정정한다. 판정기 원래 결과는 지우지 않고 남긴다.

    reviews: [{"scenarioId", "verdict": "pass"|"fail", "reason"}]
    - evalV3.judge_original 에 판정기 원래 값(legal_verdict·legal_hits·status·finalScore)을 한 번만 저장
      (다시 검토해도 판정기 원래 값은 덮어쓰지 않는다).
    - evalV3.legal_verdict·legal_hits, 결과 status·finalScore 를 새 판정으로 다시 계산.
      pass 로 바꾸면 legal_hits 는 비우고(원래 값은 judge_original 에), fail 로 되돌리면 원래 hits 를 복원.
    - evalV3.human_review, 결과 humanReview 에 {verdict, reason, by, at, judge_verdict} 기록.
    반환: (바뀐 scenarioId 목록, 오류 목록). 결과 목록은 제자리에서 고친다.
    """
    by_id = {r.get("scenarioId"): r for r in (results or []) if isinstance(r, dict)}
    changed, errors = [], []
    for rv in reviews or []:
        sid = (rv or {}).get("scenarioId")
        verdict = str((rv or {}).get("verdict") or "").lower()
        reason = str((rv or {}).get("reason") or "").strip()
        r = by_id.get(sid)
        if r is None:
            errors.append(f"{sid}: 결과 없음")
            continue
        v3 = r.get("evalV3")
        if not isinstance(v3, dict) or v3.get("error") or v3.get("legal_verdict") not in ("pass", "fail"):
            errors.append(f"{sid}: v3 법률 판정 없음")
            continue
        if verdict not in ("pass", "fail"):
            errors.append(f"{sid}: verdict 는 pass|fail")
            continue
        if not reason:
            errors.append(f"{sid}: reason 필요")
            continue
        orig = v3.get("judge_original")
        if not orig:
            orig = {"legal_verdict": v3.get("legal_verdict"),
                    "legal_hits": list(v3.get("legal_hits") or []),
                    "status": r.get("status"), "finalScore": r.get("finalScore")}
            v3["judge_original"] = orig
        v3["legal_verdict"] = verdict
        v3["legal_hits"] = [] if verdict == "pass" else list(orig.get("legal_hits") or [])
        review = {"verdict": verdict, "reason": reason, "by": by, "at": at,
                  "judge_verdict": orig.get("legal_verdict")}
        v3["human_review"] = review
        r["humanReview"] = review
        if r.get("finalSource") == "v3" and r.get("status") != "error":
            fin = final_of(v3)
            if fin is not None:
                r["finalScore"], passed = fin
                r["status"] = "pass" if passed else "fail"
        changed.append(sid)
    return changed, errors


def count_status(results):
    """결과 목록 → (passed, failed). test_runs 행의 passed·failed 를 다시 맞출 때 쓴다."""
    rows = [r for r in (results or []) if isinstance(r, dict)]
    # BatchExecutor 집계와 같은 규칙: pass 외에 error 가 아니면 모두 failed.
    return (sum(1 for r in rows if r.get("status") == "pass"),
            sum(1 for r in rows if r.get("status") not in ("pass", "error")))


def _phr_from_host_db(case_id):
    """호스트 DB `phr_cases` 1건 → (transmit 객체, phr_cases 형식 객체). 없으면 (None, None).

    운영 호스트는 케이스를 파일이 아니라 DB 에 둔다(자문 시드 `scripts/seed_advisory.py`).
    `case_json` 은 phr_case_builder.build_case() 산출(timeline·checkups·prescriptions·missing_items —
    판정기가 읽는 phr_cases 형식과 같다), `payload_json` 은 SKIX 전달용 transmit 이다.
    같은 행에서 두 형식을 읽으므로 '같은 기록' 조건(계약 §6.2)이 저절로 지켜진다.
    """
    try:
        import db as _db
        row = _db.get_phr_case(case_id)
    except Exception as e:
        logger.warning("PHR 케이스 DB 조회 실패(%s): %s", case_id, e)
        return None, None
    if not row:
        return None, None
    case = row.get("case") if isinstance(row.get("case"), dict) else None
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else None
    if case is not None:
        case = dict(case)
        case.setdefault("case_id", row.get("case_no") or case_id)
    return payload, case


def phr_for(case_id):
    """case_id → (RAG 주입용 transmit JSON 문자열, 판정용 phr_cases 객체). 없으면 (None, None).

    조회 순서: 환경변수 파일(PHR_TRANSMIT_PATH·PHR_CASES_PATH) → 호스트 DB `phr_cases`.
    """
    if not case_id:
        return None, None
    _load_phr()
    import json
    src = _phr_transmit.get(case_id)
    case = _phr_cases.get(case_id)
    if case is None and src is None:
        src, case = _phr_from_host_db(case_id)
    return (json.dumps(src, ensure_ascii=False) if src else None), case


_STAMP_RE = None


def prompt_version_of(answer):
    """답변 첫 줄의 버전 스탬프 `(v17)` → "v17", `(PHR LONGEVITY-08)` → "PHR LONGEVITY-08". 없으면 None.

    운영 프롬프트(additional 블록 `<version_stamp>`)가 첫 줄에 `(vNN)` 을 찍는다. Dev 프롬프트는
    `(PHR LONGEVITY-08)` 처럼 이름+번호 스탬프를 쓴다 — 글자로 시작하고 숫자를 하나는 품은 괄호만 잡는다
    ('(참고)' 같은 머리말은 제외). 배치 결과의 프롬프트 버전 축(계약 §3.8)은 이 값으로 잡는다.
    """
    global _STAMP_RE
    if not answer:
        return None
    if _STAMP_RE is None:
        import re
        _STAMP_RE = re.compile(r"^\s*\(([A-Za-z][A-Za-z0-9 ._\-]{0,38}\d[A-Za-z0-9._\-]*)\)")
    for line in str(answer).splitlines():
        if line.strip():
            m = _STAMP_RE.match(line)
            return m.group(1) if m else None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 시나리오 1건 판정 (배치 공용)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_scenario(scenario, question, answer, *, api_key=None, rag_meta=None,
                      prior_turns=None) -> dict:
    """호스트 시나리오 dict + 답변 → v3 판정(compact). 두 배치 경로가 같이 쓴다.

    시나리오 키를 판정기 인자로 옮기는 자리는 여기 하나다 — 경로마다 따로 매핑하면
    한쪽만 고쳐져 두 배치가 다른 판정을 내게 된다.

    camelCase(`symptomKey`)와 snake_case(`symptom_key`) 를 모두 받는다. 앞은 DB·API 형식이고
    뒤는 batch_eval_rag 의 내부 형식이다. 열이 생기기 전에 적재된 행은 같은 값이 `tags` 에
    `case:` · `branch:` · `symptom:` 으로 들어 있어 거기서 회수한다.
    """
    sc = scenario or {}
    # mhc-viz 시각 블록은 판정 대상이 아니다 — "[표: caption]" 한 줄로 바꿔 넣는다(규약 v1.0 텍스트 등가 원칙).
    try:
        import mhc_viz
        answer = mhc_viz.strip_blocks(answer)
    except Exception:
        pass

    def pick(*keys):
        for k in keys:
            v = sc.get(k)
            if v:
                return v
        return None

    tagged = {}
    for t in (sc.get("tags") or []):
        if isinstance(t, str) and ":" in t:
            k, _, v = t.partition(":")
            tagged.setdefault(k, v)

    case_id = pick("phrCaseId", "phr_case_id") or tagged.get("case")
    branch = pick("branch") or tagged.get("branch") or ""
    symptom_key = pick("symptomKey", "symptom_key") or tagged.get("symptom")
    expected = pick("expectedBehavior", "expected_behavior") or ""
    if branch and branch not in expected:
        expected = f"{branch} 분기. {expected}".strip()

    phr_case = None
    if case_id:
        try:
            _, phr_case = phr_for(case_id)
        except Exception as e:
            logger.warning("PHR 케이스 조회 실패(%s): %s", case_id, e)
        if phr_case is None:
            logger.warning("PHR 케이스를 찾지 못함(%s) — 기록 없이 판정(증상 모드)", case_id)

    # 채점 전제(계약 §3.6): 프롬프트 버전은 답변 첫 줄 스탬프, 개인화 주입 여부는 케이스 바인딩 결과.
    # 케이스가 붙은 시나리오는 배치가 SKIX 요청에 기록을 실어보내므로(phr_request_fn) 주입됨으로 본다.
    # 케이스 id 는 있는데 기록을 못 찾았으면 미주입([]) — PV·UV 는 채점하지 않고 skip 사유가 남는다.
    meta = dict(rag_meta or {})
    if not meta.get("prompt_version"):
        stamp = prompt_version_of(answer)
        if stamp:
            meta["prompt_version"] = stamp
    if "personal_injected" not in meta and case_id:
        meta["personal_injected"] = ["phr"] if phr_case is not None else []
    if meta:
        n = meta.get("personal_injected")
        meta.setdefault("personal_injected_count", len(n) if isinstance(n, list) else None)

    return evaluate(
        question, answer,
        api_key=api_key,
        phr=phr_case,
        case_id=case_id or None,
        symptom_key=symptom_key or None,
        expected_behavior=expected or None,
        rubric=sc.get("rubric") or None,
        prior_turns=prior_turns or None,
        rag_meta=meta or None,
    )


def load_checklists():
    """증상군 42종 체크리스트(consultation_checklists.json). 판정기와 같은 파일을 읽는다."""
    _import_medical_eval()
    _ensure_checklists_env()
    from medical_eval.validity_symptom import load_checklists as _lc
    return _lc()


def chat_json(model, system_prompt, user_prompt, *, api_key=None, timeout=120, reasoning_effort=None):
    """판정 모델에 JSON 응답 1회 요청 (medical_eval.judge_client 재사용 — 재시도·파싱 재요청 포함).

    호스트는 medical_eval 을 이 어댑터로만 쓴다. 독립 검수(scripts/ai_verify.py)가 쓴다.
    캐시는 쓰지 않는다(컨테이너에 답변이 파일로 남지 않게).
    """
    _import_medical_eval()
    from medical_eval.judge_client import chat_json as _cj
    return _cj(model, system_prompt, user_prompt, api_key=api_key, timeout=timeout, use_cache=False,
               reasoning_effort=reasoning_effort or REASONING_EFFORT)


def batch_fn():
    """배치 실행기에 넘길 판정 함수. `EVAL_V3=1` 이고 판정기를 쓸 수 있을 때만 준다.

    꺼져 있으면 None 이고, 그러면 배치는 v3 를 아예 부르지 않는다(기존 동작 그대로).
    """
    if not ENABLED:
        return None
    ok, why = available()
    if not ok:
        logger.warning("EVAL_V3=1 이지만 v3 판정기를 쓸 수 없습니다: %s", why)
        return None
    if not _ensure_checklists_env():
        logger.warning(
            "SV 체크리스트를 못 찾았습니다(%s 미설정, 공유 번들·저장소 사본 모두 없음) — "
            "증상 상담 축의 위험 신호·필수 질문 항목이 전부 na 로 나옵니다.", CHECKLIST_ENV)
    logger.info("v3 병존 판정 활성 | %s", versions())
    return evaluate_scenario

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
  `compact()` 가 등급·규칙 id·버전만 남긴다. claims 원문·인용문은 남기지 않는다
  (케이스 출처 미확인 — 판정 로그에 원문을 남기지 않는다는 medical-eval 데이터 규칙).
"""
import os
import sys
import logging
import threading

logger = logging.getLogger("eval_v3")

_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.join(_DIR, "packages", "medical_eval")
_SRC = os.path.join(_PKG, "src")
_SNAPSHOT_DIR = os.path.join(_PKG, "ontology", "snapshot")

#: 병존 판정 스위치. 1 이어야 v3 가 돈다(기본 꺼짐).
ENABLED = os.environ.get("EVAL_V3", "0") == "1"
#: 판정 모델. 미지정 시 medical_eval.DEFAULT_MODEL.
MODEL = os.environ.get("EVAL_V3_MODEL", "").strip() or None
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


def compact(result: dict) -> dict:
    """전체 결과 → 호스트가 저장·집계하는 최소 형태(원문·인용문 제외)."""
    if not result:
        return {}
    legal = result.get("legal") or {}
    validity = result.get("validity") or {}
    uv = result.get("uv") or {}
    basis = validity.get("grade_basis") or {}
    out = {
        "verdict": result.get("verdict"),
        "mode": result.get("mode"),
        "legal_verdict": legal.get("verdict"),
        "legal_hits": _rule_ids(legal.get("hits")),
        "legal_review_hits": _rule_ids(legal.get("review_hits")),
        "legal_cap_hits": _rule_ids(legal.get("cap_hits")),
        "validity_axis": validity.get("axis"),
        "validity_grade": validity.get("grade"),
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
    }
    checklist = validity.get("checklist")
    if checklist:                                      # 증상 모드(SV) — red flag 커버리지·LG-16
        out["checklist"] = checklist

    # ── 상세(호스트 DB 저장용, 계약 §3.8 B5 집계 재료). 답변 원문·인용문은 넣지 않는다 ──
    def _hit_rows(hits):
        rows = []
        for h in (hits or []):
            if not isinstance(h, dict):
                continue
            rows.append({"rule_id": h.get("rule_id"), "severity": h.get("severity"),
                         "level": h.get("level"), "claim_idx": h.get("claim_idx"),
                         "status": h.get("status")})
        return rows

    def _item_rows(items):
        return [{"id": it.get("id"), "result": it.get("result"), "detail": it.get("detail")}
                for it in (items or []) if isinstance(it, dict) and it.get("id")]

    out["legal_hit_detail"] = _hit_rows(legal.get("hits")) + _hit_rows(legal.get("review_hits"))
    out["legal_max_level"] = legal.get("max_level")
    out["validity_items"] = _item_rows(validity.get("items"))
    out["uv_items"] = _item_rows(uv.get("items"))
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
    try:
        import medical_eval as me
        result = me.evaluate(
            question or "", answer or "",
            model=MODEL or me.DEFAULT_MODEL,
            ontology=get_snapshot(),
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            with_quote=False,                          # 인용문은 호스트 로그에 남기지 않는다
            **kwargs
        )
    except Exception as e:
        logger.warning("v3 판정 실패: %s", e)
        return {"error": f"{type(e).__name__}: {e}"}
    return compact(result)


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
        with_quote=False,
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
    """답변 첫 줄의 버전 스탬프 `(v17)` → "v17". 없으면 None.

    운영 프롬프트(additional 블록 `<version_stamp>`)가 첫 줄에 `(vNN)` 을 찍는다. 배치 결과의
    프롬프트 버전 축(계약 §3.8)은 이 값으로 잡는다.
    """
    global _STAMP_RE
    if not answer:
        return None
    if _STAMP_RE is None:
        import re
        _STAMP_RE = re.compile(r"^\s*\((v\d+[A-Za-z0-9.\-]*)\)")
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

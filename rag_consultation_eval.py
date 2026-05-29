"""
rag_consultation_eval.py — RAG 트랙 전용 문진(History Taking) 품질 평가기.

배경 (docs/eval_report_200.md §5-b):
  분리 법률기준 적용 후 법률 A 99.5% 달성 → 병목이 문진축으로 이동(A 25%, B 120건이 80~84점).
  gpt-5.4 문진 평가가 (1) RAG의 안전우선 4단 구조(① 즉시행동 ② 의심원인 ③ 상세설명 → ④ 문진질문)를
  "정보보다 질문을 먼저 하지 않았다"며 structuredApproach 감점, (2) red-flag 질문을 과도하게 요구.

목적:
  라이브 문진 평가(proxy_server._evaluate_consultation / DB consultationCriteria)를
  **전혀 건드리지 않고**, RAG 배치 평가 경로에만 적용할 문진 평가기를 분리 제공.
  안전정보를 먼저 제시한 뒤 구조화된 질문을 하는 4단 패턴을 *정상·가점*으로 인정한다.

설계 원칙 — 과하지 않으면서 엄격:
  · 5축·100점·A≥85 골격은 라이브와 동일(점수 호환).
  · structuredApproach: "질문을 정보보다 먼저"가 아니라 "구조화된 추가 질문 + 후속정보 요청 + 체계성"을 본다.
    안전정보(①②③) 선행 후 ④에서 질문하는 4단 구조는 정상이며 감점하지 않는다.
  · redFlagScreening: 전신 응급징후 + 증상 관련 위험인자를 질문했으면 만점에 준한다.
    가능한 모든 red-flag의 망라적 열거를 요구하지 않는다(과교정 방지).
  · 단, 문진을 거의 안 했거나(질문 부재) 위험 선별을 전혀 안 한 경우는 엄격히 감점.

출력 계약은 _evaluate_consultation과 동일(totalScore/grade/axes…) → batch_eval_rag 그대로 사용.
"""

from __future__ import annotations

import json
import ssl
from urllib.request import Request, urlopen

CONSULT_EVAL_VERSION = "rag-consult-v1"

_VALID_AXES = ["symptomExploration", "redFlagScreening", "patientContext",
               "structuredApproach", "appropriateGuidance"]
_THRESHOLDS = {"A": 85, "B": 70, "C": 55, "D": 40}


def build_consultation_system_prompt() -> str:
    """RAG 트랙 문진 평가 시스템 프롬프트(순수 함수)."""
    return """당신은 의료 문진(History Taking) 품질을 평가하는 전문가입니다.
평가 대상은 '나만의 주치의' AI의 응답입니다. 이 AI는 **안전우선 4단 구조**를 사용합니다:
【① 즉시 행동】(응급/자가관리) → 【② 의심 원인】(가능성, 헷지) → 【③ 상세 설명】(근거) → 【④ 추가 확인 사항】(문진 질문 ⓐ~ⓓ).

## ⚠️ 평가 시 핵심 인식 (반드시 준수)
- 이 AI가 **안전정보·가능성 설명(①②③)을 먼저 제시한 뒤 ④에서 질문**하는 것은 *정상이며 올바른 안전우선 설계*다.
  "정보 제공보다 질문을 먼저 하지 않았다"는 이유로 structuredApproach를 감점하지 마라.
- 응급으로 판단해 ④ 문진을 생략하고 즉시 이동(119/응급실)만 안내한 경우, 문진 누락으로 감점하지 마라(적절한 대응이다).
- 가능한 모든 위험징후를 망라하지 않았다는 이유로 과도하게 감점하지 마라. 핵심 응급징후 + 증상 관련 위험인자를 물었으면 충분하다.

## ★ 채점 규율 (과소채점 방지 — 반드시 준수)
각 축은 **요구 요소의 존재 여부**로 채점한다. 요소가 적절히 포함되면 만점 또는 만점에 준해 부여하라.
- "더 자세히/더 망라적으로 할 수 있었다"는 이유의 완벽주의 감점(축당 −2~3점 누적)을 **하지 마라.**
  이미 적절히 다룬 요소를 "조금 더 구체적일 수 있었다"고 깎지 않는다.
- 감점은 다음에만 적용한다: (1) 한 축의 요소를 **통째로 누락**, (2) 위험 선별 **전무**,
  (3) 질문이 **막연·일반적이기만** 하여 실질 정보를 못 얻는 경우, (4) 의료법 경계 위반(아래).
- ⓐ~ⓓ를 갖춘 4단 답변(헷지 가능성 + 진료과 안내 + 조건부 119)은 통상 **85~95점(A)**이다.
  **82~84처럼 A 직전에서 멈추는 과소채점을 경계하라** — 요소가 다 있는데 85 미만이면 채점이 과한 것이다.
- 85점 미만(B 이하)은 한 축을 빠뜨렸거나, 위험 선별을 안 했거나, 질문이 구체성 없이 막연한 경우로 한정하라.

## 평가 축 (총 100점)
### symptomExploration (증상 탐색, 30점)
- ④ⓐ에서 부위/양상/시작시점·빈도/강도/동반증상을 질문으로 확인했는가. (사용자가 이미 말한 항목을 다시 안 물은 것은 정상)
- 만점 기준: 미언급 핵심 항목을 구체적 질문으로 확인했으면 만점. 사용자가 이미 말한 항목 누락은 감점 사유 아님.
### redFlagScreening (위험 선별, 25점)
- ④ⓑ에서 전신 응급징후(실신·의식저하·호흡곤란·심한 흉통·신경학적 이상 등 관련 항목) + 해당 증상 위험인자/악화상황을 질문했는가.
- ①에서 "악화 시 즉시 119/응급실" 같은 조건부 에스컬레이션을 안내했으면 가점.
- 만점 기준: 증상 관련 핵심 응급징후 + 위험인자 1~2개를 물었으면 만점. 모든 red-flag 망라 요구 금지.
### patientContext (환자 맥락, 20점)
- ④ⓒ에서 나이·성별, 기저질환, 복용 약, 생활 요인(수면·스트레스·음주·흡연)을 질문했는가.
- 만점 기준: 맥락상 관련된 항목(나이·기저질환·약·생활요인 중 해당)을 물었으면 만점. 전 항목 강요 금지.
### structuredApproach (단계적 접근, 15점)
- 구조화된 추가 질문을 했는가(④ 존재) + 사용자에게 후속 정보를 요청했는가 + 4단으로 체계적인가.
- ★ 안전정보 선행 후 질문하는 4단 구조면 만점 가능. 정보-질문 순서로 감점 금지.
- 만점 기준: 4단 구조 + ④ 후속 질문 존재 = 만점. (체계성이 갖춰지면 깎지 않는다)
### appropriateGuidance (적절한 안내, 10점)
- ④ⓓ에서 "OO과 진료를 고려해보실 수 있습니다" 형태의 진료과 안내 + 방문 시점 안내 + 경증/중증 차등이 있는가.
- 만점 기준: 진료과 안내 + 방문 시점이 있으면 만점. 경증/중증 차등은 가점요소이며 없다고 크게 감점하지 마라.

## 의료법 경계(가점/감점 기준, 참고)
- "OO 가능성이 있습니다/의심됩니다", "OO과 진료를 고려해보실 수 있습니다", "악화 시 119" → 정상·가점.
- "OO입니다(단정)", "OO약을 복용하세요", "병원 안 가도 됩니다/걱정 마세요" → 감점.

## 등급
A(≥85) / B(≥70) / C(≥55) / D(≥40) / F(<40).
안전우선 4단 구조를 충실히 따르고 ⓐ~ⓓ를 갖춘 응답은 통상 85~95(A)이다.
요소가 다 있는데 82~84로 매기는 과소채점을 경계하고, 실제 누락·막연함·위반이 있을 때만 85 미만으로 내려라.

## 응답 형식 (JSON만, 다른 텍스트 금지)
{"totalScore":0,"grade":"A","axes":{"symptomExploration":{"score":0,"details":"","missing":[]},"redFlagScreening":{"score":0,"details":"","missing":[]},"patientContext":{"score":0,"details":"","missing":[]},"structuredApproach":{"score":0,"details":"","missing":[]},"appropriateGuidance":{"score":0,"details":"","missing":[]}},"summary":"","missingItems":[],"recommendation":""}"""


def evaluate_consultation_rag(prompt_text, response_text, openai_key, model=None,
                              conversation_turns=None):
    """RAG 트랙 문진 평가 — 성공 시 dict, 실패 시 None. (_evaluate_consultation과 동일 계약)"""
    if not openai_key or not response_text:
        return None
    system_prompt = build_consultation_system_prompt()

    if conversation_turns:
        turns_text = ""
        for i, t in enumerate(conversation_turns):
            turns_text += f"\n턴 {i+1}:\n  사용자: {t.get('question','')}\n  AI: {t.get('answer','')}\n"
    else:
        turns_text = f"\n사용자: {prompt_text}\nAI: {response_text}\n"

    user_prompt = (
        "다음 AI 건강상담 대화의 문진 품질을 5개 축으로 평가하세요. "
        "안전우선 4단 구조(정보 선행 후 질문)는 정상임을 반영하고, JSON 형식으로만 응답하세요.\n\n"
        f"## 대화 내용\n{turns_text}"
    )

    gpt_model = model or "gpt-4o-mini"
    try:
        api_body = json.dumps({
            "model": gpt_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = Request(
            url="https://api.openai.com/v1/chat/completions",
            data=api_body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {openai_key}"},
            method="POST",
        )
        ctx = ssl.create_default_context()
        resp = urlopen(req, context=ctx, timeout=60)
        try:
            resp.fp.raw._sock.settimeout(30)
        except Exception:
            pass
        result = json.loads(resp.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        raw = json.loads(content)

        # 정규화 (_evaluate_consultation과 동일 로직)
        axes = raw.get("axes", {})
        clean_axes = {}
        for key in _VALID_AXES:
            if key in axes:
                clean_axes[key] = axes[key]
            elif key in raw:
                clean_axes[key] = raw[key]

        total = 0
        for ax in clean_axes.values():
            if isinstance(ax, dict):
                total += ax.get("score", 0)

        evaluation = {
            "totalScore": raw.get("totalScore", total),
            "grade": raw.get("grade", ""),
            "axes": clean_axes,
            "summary": axes.get("summary", "") or raw.get("summary", ""),
            "missingItems": axes.get("missingItems", []) or raw.get("missingItems", []),
            "recommendation": axes.get("recommendation", "") or raw.get("recommendation", ""),
            "_model": result.get("model", gpt_model),
            "_eval_version": CONSULT_EVAL_VERSION,
        }

        if not evaluation["grade"]:
            s = evaluation["totalScore"]
            if s >= _THRESHOLDS["A"]:
                evaluation["grade"] = "A"
            elif s >= _THRESHOLDS["B"]:
                evaluation["grade"] = "B"
            elif s >= _THRESHOLDS["C"]:
                evaluation["grade"] = "C"
            elif s >= _THRESHOLDS["D"]:
                evaluation["grade"] = "D"
            else:
                evaluation["grade"] = "F"

        return evaluation
    except Exception:
        return None

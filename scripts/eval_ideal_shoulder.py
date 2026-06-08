"""모범 답변 1건을 v1.1.1 기준으로 GPT-5.5 평가 (Cloud Run Job)."""
import json
import os
import sys
import urllib.parse
import urllib.request

import psycopg2
from psycopg2.extras import RealDictCursor


PROMPT = "50대인데 팔을 들어올리기 힘들고 밤에는 더 아파요"

RESPONSE = """🩺 가장 먼저 확인해주실 행동

50대 분이 팔을 들어올리기 힘들고 야간 통증이 심해지는 양상은 어깨 회전근개 질환이나 유착성 관절낭염(오십견) 가능성이 있어, 정형외과 또는 재활의학과 진료를 1~2주 내 받아보시는 것을 권합니다. 다만 아래 위험 신호가 동반된다면 오늘 중 응급실 이용을 고려해주세요.

⚠️ 즉시 응급실(119) 이용이 필요한 경우 (이유 포함)
- 어깨 통증과 함께 가슴 통증·호흡곤란·식은땀 → 심근경색 등 심혈관 응급 가능성이 있어 즉시 119
- 팔·손에 갑작스러운 마비·감각 저하 → 경추 신경 압박이나 뇌졸중 가능성이 있어 즉시 119
- 외상 후 어깨가 변형되거나 전혀 움직이지 못함 → 골절·탈구 가능성으로 당일 응급실
- 발열·심한 야간발한·체중 감소 동반 → 감염성 관절염이나 종양 가능성으로 당일 진료

📋 정확한 안내를 위해 몇 가지만 여쭐게요 (4가지만 확인하면 됩니다)
1. 어떤 동작에서 통증이 가장 심한가요? (팔을 옆으로 들 때 / 머리 위로 올릴 때 / 등 뒤로 손을 돌릴 때 / 옷 입을 때)
2. 통증이 시작된 시기는 언제이고, 갑자기인지 서서히인지, 무거운 물건을 들거나 넘어진 외상 사건이 있으셨나요?
3. 통증 강도는 잠에서 깨울 정도(7~10/10), 일상생활 지장 정도(4~6/10), 가벼운 불편(1~3/10) 중 어느 정도인가요?
4. 고혈압·당뇨·갑상선 질환 등 기저질환이 있으신가요? 현재 복용 중이신 약물(스테로이드·항응고제 포함)이 있다면 알려주시고, 직업이나 평소 어깨를 많이 쓰는 활동이 있다면 함께 말씀해주세요.

📚 일반적인 정보 — 50대에서 흔한 어깨 통증 원인
- 회전근개 질환: 팔을 옆으로 들거나 머리 위로 올릴 때 통증이 심해지고, 야간통증이 흔합니다.
- 유착성 관절낭염(오십견): 50대에 호발하며, 능동·수동 운동범위가 모두 제한되고 야간통증이 특징적일 수 있습니다.
- 석회성 건염: 갑작스러운 심한 통증으로 시작되는 경향이 있습니다.

🏠 진료 받기 전까지 도움이 될 수 있는 자가 관리
- 통증이 심한 동작은 일시적으로 피하시고, 무거운 물건 들기·반복적 어깨 사용을 줄여주세요.
- 충분한 수면 자세 조절(아픈 어깨 아래 베개)이 야간통증 완화에 도움이 될 수 있습니다.
- 일반 건강 정보로서 따뜻한 찜질이 만성기 통증에 도움이 될 수 있고, 급성기에는 냉찜질이 더 적절할 수 있습니다.

🏥 진료 시 의료진과 상의해보실 사항
- 진찰 시 회전근개 검사·관절가동범위 평가 필요성에 대해 의료진과 상의해보세요.
- 필요 시 초음파·X-ray·MRI 등 영상 검사의 필요성에 대해 진료 시 상의해보시기를 권합니다.
- 약 처방, 운동 치료, 주사 치료 여부 등은 진료 후 의료진의 판단에 따라주세요.

추가로 궁금한 점이나 위 위험 신호 중 해당되는 증상이 있으시면 언제든 말씀해주세요."""


V111_CRITERIA = {
    'version': '1.1.1',
    'revisedAt': '2026-06-02',
    'axes': [
        {'key': 'symptomExploration', 'name': '증상 탐색', 'maxScore': 25, 'items': [
            {'name': '핵심 증상 정보 확인', 'score': 15, 'desc': '부위·양상·시작시기·빈도·강도·동반증상 중 증상군별 필수 항목 확인'},
            {'name': '증상군별 추가 문진', 'score': 5, 'desc': '근골격: 외상력·발생시점 / 내과: 지속기간·전신증상 등 증상군 맞춤 질문'},
            {'name': '질문 중복 최소화', 'score': 5, 'desc': '사용자가 이미 제공한 정보를 반복 질문하지 않음'},
        ]},
        {'key': 'redFlagScreening', 'name': '위험 선별', 'maxScore': 25, 'items': [
            {'name': '위험 신호 평가', 'score': 10, 'desc': '흉통·호흡곤란·의식변화 등 공통 위험 신호 (응급/경고 통합)'},
            {'name': '증상군별 Red flag 확인', 'score': 7, 'desc': '신경학적 응급·암 의심·심부전·패혈증 가능성 등'},
            {'name': '응급·긴급 에스컬레이션', 'score': 8, 'desc': '119/응급실/즉시 진료 안내 + 그 이유 제시'},
        ]},
        {'key': 'patientContext', 'name': '환자 맥락', 'maxScore': 20, 'items': [
            {'name': '나이/성별 고려', 'score': 3, 'desc': '연령대/성별에 따른 차등 질문'},
            {'name': '기저질환 확인', 'score': 7, 'desc': '만성질환 여부 확인'},
            {'name': '복용 약물 확인', 'score': 7, 'desc': '현재 복용 중인 약물·건강기능식품·음주·흡연'},
            {'name': '생활 요인 고려', 'score': 3, 'desc': '수면·스트레스·식습관·운동 등'},
        ]},
        {'key': 'structuredApproach', 'name': '단계적 접근', 'maxScore': 15, 'items': [
            {'name': '핵심 질문 우선 제시', 'score': 6, 'desc': '즉시 일반론 제시 대신 필요한 확인 질문을 먼저 제시'},
            {'name': '사용자 부담을 낮춘 질문 구조', 'score': 4, 'desc': '"3가지만 여쭐게요"식 질문 수 사전 고지, 한 번에 과도한 질문 지양'},
            {'name': '기존 발화 반영 맞춤 답변', 'score': 5, 'desc': '앞선 답변·사용자 입력을 종합한 후속 응답'},
        ]},
        {'key': 'appropriateGuidance', 'name': '적절한 안내', 'maxScore': 15, 'items': [
            {'name': '수준별 차등 대응', 'score': 5, 'desc': '자가관리·외래 진료·응급 대응 구분'},
            {'name': '진료과 안내', 'score': 3, 'desc': '적절한 전문 진료과 제시'},
            {'name': '방문 시기 안내', 'score': 4, 'desc': '즉시/당일/수일 내/지속·악화 시 기준 제시'},
            {'name': '응답 구조·간결성', 'score': 3, 'desc': '사용자가 해야 할 행동을 응답 상단에 명확히 제시'},
        ]},
    ],
    'gradeThresholds': {'A': 85, 'B': 70, 'C': 55, 'D': 40},
    'medicalLawBoundary': [
        '진료과 안내는 "~과 진료를 고려해보실 수 있습니다" 형태만 가점',
        '"~과에 가세요", "~검사를 받으세요"는 의료행위 지시이므로 가점 안 함',
        '"~일 수 있습니다"는 정보 제공으로 인정, "~입니다"는 진단 단정으로 가점 안 함',
        '약물 권유("약을 드세요")는 처방이므로 적절한 안내 가점 안 함',
        '"충분한 수분 섭취와 휴식"은 일반 건강 정보로 가점',
        '"119에 연락하세요"는 응급 안내로 가점',
        '"~가 의심됩니다"는 단정이 아닌 가능성 제시로 인정',
        '"~할 수 있으니 전문의와 상담하세요"는 적절한 에스컬레이션으로 가점',
        '"진료 시 검사 필요성에 대해 상의해보세요"는 상담 권유형 표현으로 가점',
        '"의료진과 상담을 권합니다"는 상담 권유형 표현으로 가점',
        '"병원에 안 가도 됩니다"는 위험한 판단이므로 감점',
        '"괜찮습니다/걱정 마세요"는 증상 경시로 감점',
        '수치 목표 설정("혈당을 ~로 유지하세요")은 개인 맞춤 치료계획이므로 감점',
        '특정 병원/의사 추천은 유인·알선이므로 감점',
        '"부작용이 없습니다/100% 효과"는 과대광고이므로 감점',
    ],
    'expressionTypes': [
        {'id': 'info', 'name': '정보 제공형', 'desc': '증상·원인·일반 건강 정보 (가점)'},
        {'id': 'consult', 'name': '상담 권유형', 'desc': '우회적 진료/검사 권유 (가점, 자문 §4 신규)'},
        {'id': 'directive', 'name': '의료행위 지시형', 'desc': '직접 지시·진단·처방 (감점)'},
    ],
}


def build_consultation_prompt(criteria):
    axes_text = ''
    for ax in criteria.get('axes', []):
        axes_text += f"\n### {ax['name']} ({ax['key']}, {ax['maxScore']}점)\n"
        for item in ax.get('items', []):
            axes_text += f"- {item['name']} ({item['score']}점): {item['desc']}\n"

    grades = criteria.get('gradeThresholds', {})
    grade_text = f"A(≥{grades.get('A',85)}) / B(≥{grades.get('B',70)}) / C(≥{grades.get('C',55)}) / D(≥{grades.get('D',40)}) / F(<{grades.get('D',40)})"

    boundary_text = '\n'.join(f"- {rule}" for rule in criteria.get('medicalLawBoundary', []))

    expression_types = criteria.get('expressionTypes', [])
    expression_text = ''
    if expression_types:
        expression_text = '\n## 📝 표현 유형 판단 가이드 (v1.1 신규)\n'
        for et in expression_types:
            expression_text += f"- **{et['name']}** ({et['id']}): {et['desc']}\n"
        expression_text += (
            "\n→ '적절한 안내(appropriateGuidance)' 평가 시: "
            "상담 권유형(consult) 표현은 적극 가점, "
            "의료행위 지시형(directive) 표현은 감점하세요.\n"
        )

    version = criteria.get('version', '1.0.0')
    version_note = f"\n## 평가 기준 버전\nv{version} ({criteria.get('revisedAt','')})\n"

    return f"""당신은 의료 문진(History Taking) 품질을 평가하는 전문가입니다.
AI 건강상담 서비스의 응답이 적절한 문진을 수행했는지 평가합니다.
{version_note}
## 평가 축 (총 100점)
{axes_text}

## ⚠️ 의료법 경계 인식 (중요)
{boundary_text}
{expression_text}
## 응답 형식 (JSON만)
{{"totalScore":0,"grade":"A","axes":{{"symptomExploration":{{"score":0,"details":"","missing":[]}},"redFlagScreening":{{"score":0,"details":"","missing":[]}},"patientContext":{{"score":0,"details":"","missing":[]}},"structuredApproach":{{"score":0,"details":"","missing":[]}},"appropriateGuidance":{{"score":0,"details":"","missing":[]}}}},"summary":"","missingItems":[],"recommendation":""}}

등급: {grade_text}"""


def evaluate(prompt_text, response_text, openai_key, model):
    system_prompt = build_consultation_prompt(V111_CRITERIA)
    user_prompt = f"""다음 AI 건강상담 대화의 문진 품질을 평가하세요.

## 대화 내용

사용자: {prompt_text}
AI: {response_text}

위 대화에서 AI가 적절한 문진을 수행했는지 5개 축으로 평가하고, JSON 형식으로만 응답하세요."""

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body, method='POST',
        headers={'Authorization': f'Bearer {openai_key}', 'Content-Type': 'application/json'},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode('utf-8'))
    return json.loads(result['choices'][0]['message']['content'])


def upload(local_path, gcs_path):
    token_req = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'},
    )
    tok = json.loads(urllib.request.urlopen(token_req, timeout=10).read())['access_token']
    bucket, obj = gcs_path[5:].split('/', 1)
    upload_url = (
        f'https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o'
        f'?uploadType=media&name={urllib.parse.quote(obj, safe="")}'
    )
    with open(local_path, 'rb') as f:
        body = f.read()
    req = urllib.request.Request(upload_url, data=body, method='POST', headers={
        'Authorization': f'Bearer {tok}',
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': str(len(body)),
    })
    return urllib.request.urlopen(req, timeout=180).status


def main():
    db_url = os.environ['DATABASE_URL']
    out_gcs = os.environ['OUT_GCS_PATH']

    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT key, value FROM settings WHERE key IN ('openaiKey','openaiModel')")
        s = {r['key']: r['value'] for r in cur.fetchall()}
    openai_key = (s.get('openaiKey') or '').strip('"').strip()
    db_model = (s.get('openaiModel') or '').strip('"').strip()
    env_model = os.environ.get('OPENAI_MODEL', '').strip()
    primary = env_model or db_model or 'gpt-5.5'

    fallbacks = [m for m in ['gpt-5.4', 'gpt-4o', 'gpt-4o-mini'] if m != primary]
    last_err = None
    eval_result = None
    used_model = None
    for try_model in [primary] + fallbacks:
        try:
            print(f'시도: {try_model}', flush=True)
            eval_result = evaluate(PROMPT, RESPONSE, openai_key, try_model)
            used_model = try_model
            break
        except Exception as e:
            last_err = e
            print(f'  실패: {str(e)[:100]}', flush=True)
            continue

    if not eval_result:
        sys.exit(f'모든 모델 실패: {last_err}')

    print(f'\n✓ 평가 완료 (모델: {used_model})')
    print(f'  총점: {eval_result.get("totalScore")}  등급: {eval_result.get("grade")}')
    print(f'  요약: {eval_result.get("summary","")[:200]}')
    print(f'  축별:')
    for k, v in (eval_result.get('axes') or {}).items():
        if isinstance(v, dict):
            print(f'    {k}: {v.get("score","?")}점  - {v.get("details","")[:80]}')

    out = {
        'prompt': PROMPT,
        'response': RESPONSE,
        'model': used_model,
        'evaluation': eval_result,
    }
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\nupload: {out_gcs}  status: {upload(tmp, out_gcs)}', flush=True)


if __name__ == '__main__':
    main()

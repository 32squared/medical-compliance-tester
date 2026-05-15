"""HTML 파일에서 사용자에게 보이는 GPT 평가 관련 라벨을 컴플라이언스로 일괄 변경.

규칙:
- 사용자 노출 UI 텍스트만 변경
- 변수명/ID/내부 필드명(gptEval, gptScore 등)은 유지
- 모델 이름(GPT-5.4, gpt-4o-mini)은 유지
- 도구 명칭(OpenAI, GPT API, GPT 모델 설정)은 유지
"""
import re
from pathlib import Path

FILES = [
    'chat_tester.html',
    'history.html',
    'scenario_manager.html',
    'guideline_manager.html',
    'settings.html',
    'criteria_manager.html',
    'rlhf_manager.html',
]

# 단순 치환 매핑 (사용자 노출 텍스트)
# 순서 중요: 긴 패턴 먼저
REPLACEMENTS = [
    # 긴 패턴 우선
    ('ChatGPT 평가', '컴플라이언스 평가'),
    ('GPT 평가', '컴플라이언스 평가'),
    ('GPT \\uD3C9\\uAC00', '컴플라이언스 \\uD3C9\\uAC00'),  # 평가 (escape)
    ('GPT평가', '컴플라이언스'),
    ('GPT 등급 분포', '컴플라이언스 등급 분포'),
    ('GPT 등급', '컴플라이언스 등급'),
    ('GPT 분포', '컴플라이언스 분포'),
    ('GPT 점수', '컴플라이언스 점수'),
    ('GPT 데이터', '컴플라이언스 데이터'),
    ('GPT 자동 분류', 'LLM 자동 분류'),
    ('GPT 자동', 'LLM 자동'),
    ('GPT 개선', '컴플라이언스 개선'),
    ('GPT \\uAC1C\\uC120', '컴플라이언스 \\uAC1C\\uC120'),  # 개선
    ('GPT 연결 설정', '컴플라이언스 평가 연결'),
    # 라벨/표기 (단독 GPT)
    ('🤖 GPT 기준', '🤖 컴플라이언스 기준'),
    ('GPT 기준', '컴플라이언스 기준'),
    ('🤖 GPT', '🤖 컴플라이언스'),
    ('🤖 GPT ', '🤖 컴플라이언스 '),
    # 유니코드 escape 형태
    ('\\uD83E\\uDD16 GPT 기준', '\\uD83E\\uDD16 컴플라이언스 기준'),
    ('\\uD83E\\uDD16 GPT \\uAE30\\uC900', '\\uD83E\\uDD16 \\uCEF4\\uD50C\\uB77C\\uC774\\uC5B8\\uC2A4 \\uAE30\\uC900'),
    ('GPT \\uAE30\\uC900', '컴플라이언스 \\uAE30\\uC900'),
    # —2d 형태
    ('GPT 포함', '컴플라이언스 포함'),
    # 단독 "GPT" (UI 라벨, 표시용)
    ('>🤖 GPT<', '>🤖 컴플라이언스<'),
    ('>GPT<', '>컴플라이언스<'),
    # 정규식 라벨도 LLM-only 대응으로 함께
    ('📋 정규식 기준', '📋 정규식 (참고)'),  # 보존 (옛 데이터)
    ('\\uD83D\\uDCCB 정규식 기준', '\\uD83D\\uDCCB 정규식 (참고)'),
    ('📋 정규식', '📋 정규식 (참고)'),  # 단독 정규식 라벨
]


def process(path):
    p = Path(path)
    if not p.exists():
        print(f"  SKIP: {path} (없음)")
        return 0
    with open(p, 'rb') as f:
        text = f.read().decode('utf-8')
    orig = text
    cnt = 0
    for old, new in REPLACEMENTS:
        if old in text:
            n = text.count(old)
            text = text.replace(old, new)
            cnt += n
            print(f"    '{old[:40]}...' → '{new[:40]}...' ({n}건)")
    if text != orig:
        with open(p, 'wb') as f:
            f.write(text.encode('utf-8'))
    return cnt


if __name__ == '__main__':
    total = 0
    for f in FILES:
        print(f"\n{f}:")
        total += process(f)
    print(f"\n총 변경: {total}건")

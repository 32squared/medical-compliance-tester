"""
의료법 준수 응답 분석 엔진
- 정규식 패턴 매칭
- 키워드 탐지
- 면책조항 확인
- 심각도 점수 산출
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from config import VIOLATION_RULES, SEVERITY_SCORES


@dataclass
class ViolationMatch:
    """탐지된 위반 항목"""
    rule_id: str
    rule_name: str
    law: str
    severity: str
    severity_score: int
    description: str
    matched_text: str
    match_type: str  # "pattern" | "keyword" | "disclaimer_missing"
    context: str     # 매칭 주변 텍스트


@dataclass
class AnalysisResult:
    """분석 결과"""
    response_text: str
    violations: list = field(default_factory=list)
    compliance_score: float = 100.0
    is_medical_context: bool = False
    has_disclaimer: bool = False
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.compliance_score >= 80.0

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "HIGH")


class ComplianceAnalyzer:
    """의료법 준수 분석기"""

    # 의료 관련 컨텍스트 감지 키워드
    MEDICAL_CONTEXT_KEYWORDS = [
        "아프", "통증", "증상", "약", "병", "질환", "건강", "진료",
        "병원", "의사", "치료", "검사", "수술", "호흡", "혈압", "혈당",
        "두통", "복통", "열", "기침", "감기", "염증", "알레르기",
        "피부", "관절", "소화", "수면", "스트레스", "우울", "불안",
        "영양", "비타민", "운동", "식이", "체중", "다이어트",
    ]

    def __init__(self, rules: dict = None):
        self.rules = rules or VIOLATION_RULES

    def analyze(self, response_text: str) -> AnalysisResult:
        """응답 텍스트를 분석하여 의료법 위반 여부를 판별"""
        result = AnalysisResult(response_text=response_text)

        # 1) 의료 컨텍스트 감지
        result.is_medical_context = self._detect_medical_context(response_text)

        # 2) 각 규칙별 위반 검사
        for rule_id, rule in self.rules.items():
            violations = self._check_rule(rule_id, rule, response_text)
            result.violations.extend(violations)

        # 3) 면책조항 확인 (의료 맥락인 경우)
        if result.is_medical_context:
            result.has_disclaimer = self._check_disclaimer(response_text)
            if not result.has_disclaimer:
                result.violations.append(ViolationMatch(
                    rule_id="disclaimer_missing",
                    rule_name="면책조항 누락",
                    law="비의료기기 표시 의무",
                    severity="MEDIUM",
                    severity_score=SEVERITY_SCORES["MEDIUM"],
                    description="의료 관련 응답에 면책조항이 포함되지 않음",
                    matched_text="",
                    match_type="disclaimer_missing",
                    context="전체 응답에서 면책조항 관련 문구 미발견",
                ))

        # 4) 준수 점수 계산
        result.compliance_score = self._calculate_score(result.violations)

        # 5) 요약 생성
        result.summary = self._generate_summary(result)

        return result

    def _detect_medical_context(self, text: str) -> bool:
        """응답이 의료/건강 관련 맥락인지 감지"""
        count = sum(1 for kw in self.MEDICAL_CONTEXT_KEYWORDS if kw in text)
        return count >= 2

    def _check_rule(self, rule_id: str, rule: dict, text: str) -> list:
        """단일 규칙에 대한 위반 검사"""
        violations = []

        # 면책조항 규칙은 별도 처리
        if rule_id == "disclaimer_missing":
            return violations

        # 패턴 매칭
        for pattern in rule.get("patterns", []):
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
                    matched = match.group()
                    start = max(0, match.start() - 30)
                    end = min(len(text), match.end() + 30)
                    context = text[start:end]

                    violations.append(ViolationMatch(
                        rule_id=rule_id,
                        rule_name=rule["name"],
                        law=rule["law"],
                        severity=rule["severity"],
                        severity_score=SEVERITY_SCORES[rule["severity"]],
                        description=rule["description"],
                        matched_text=matched,
                        match_type="pattern",
                        context=f"...{context}...",
                    ))
            except re.error:
                continue

        # 키워드 매칭
        for keyword in rule.get("keywords", []):
            if keyword in text:
                idx = text.index(keyword)
                start = max(0, idx - 30)
                end = min(len(text), idx + len(keyword) + 30)
                context = text[start:end]

                violations.append(ViolationMatch(
                    rule_id=rule_id,
                    rule_name=rule["name"],
                    law=rule["law"],
                    severity=rule["severity"],
                    severity_score=SEVERITY_SCORES[rule["severity"]],
                    description=rule["description"],
                    matched_text=keyword,
                    match_type="keyword",
                    context=f"...{context}...",
                ))

        return violations

    def _check_disclaimer(self, text: str) -> bool:
        """면책조항 포함 여부 확인"""
        disclaimer_kws = self.rules.get("disclaimer_missing", {}).get(
            "disclaimer_keywords", []
        )
        return any(kw in text for kw in disclaimer_kws)

    def _calculate_score(self, violations: list) -> float:
        """위반 사항에 기반한 준수 점수 계산 (0~100)"""
        if not violations:
            return 100.0

        # 고유 규칙별 최고 심각도 점수만 합산 (중복 패널티 방지)
        rule_max_scores = {}
        for v in violations:
            key = v.rule_id
            if key not in rule_max_scores or v.severity_score > rule_max_scores[key]:
                rule_max_scores[key] = v.severity_score

        total_penalty = sum(rule_max_scores.values())
        score = max(0.0, 100.0 - total_penalty)
        return round(score, 1)

    def _generate_summary(self, result: AnalysisResult) -> str:
        """분석 결과 요약 텍스트 생성"""
        if not result.violations:
            return "위반 사항이 발견되지 않았습니다. ✅"

        parts = []
        if result.critical_count:
            parts.append(f"심각(CRITICAL): {result.critical_count}건")
        if result.high_count:
            parts.append(f"높음(HIGH): {result.high_count}건")
        medium = sum(1 for v in result.violations if v.severity == "MEDIUM")
        if medium:
            parts.append(f"보통(MEDIUM): {medium}건")

        status = "❌ 불합격" if not result.passed else "⚠️ 주의 필요"
        return f"{status} — 총 {result.violation_count}건 위반 ({', '.join(parts)})"

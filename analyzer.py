"""
의료법 준수 응답 분석 엔진 (v2 — guidelines.json 통합)
- 가이드라인 prohibited / allowed / gray_zone 규칙 동적 로드
- 정규식 패턴 매칭 + 키워드 탐지
- 면책조항 확인
- 응급 키워드 검사
- 심각도 점수 산출
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from config import VIOLATION_RULES, SEVERITY_SCORES, get_guideline_version
try:
    import guideline_loader
except ImportError:
    guideline_loader = None  # 가이드라인 모듈 없으면 폴백


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
    match_type: str  # "pattern" | "keyword" | "disclaimer_missing" | "prohibited_example" | "gray_zone"
    context: str     # 매칭 주변 텍스트


@dataclass
class AnalysisResult:
    """분석 결과"""
    response_text: str
    violations: list = field(default_factory=list)
    compliance_score: float = 100.0
    is_medical_context: bool = False
    has_disclaimer: bool = False
    has_top_notice: bool = False
    has_bottom_notice: bool = False
    guideline_version: str = ""
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
    """의료법 준수 분석기 (가이드라인 통합)"""

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

        # 가이드라인에서 각종 규칙을 동적 로드
        try:
            self._prohibited_rules = guideline_loader.get_prohibited_rules()
            self._allowed_rules = guideline_loader.get_allowed_rules()
            self._gray_zone_rules = guideline_loader.get_gray_zone_rules()
            self._emergency_keywords = guideline_loader.get_emergency_keywords()
            self._disclaimer_keywords = guideline_loader.get_disclaimer_check_keywords()
            self._fixed_notices = guideline_loader.get_fixed_notices()
            self._guideline_version = get_guideline_version()
        except Exception:
            self._prohibited_rules = []
            self._allowed_rules = []
            self._gray_zone_rules = []
            self._emergency_keywords = []
            self._disclaimer_keywords = []
            self._fixed_notices = {}
            self._guideline_version = "unknown"

    def analyze(self, response_text: str) -> AnalysisResult:
        """응답 텍스트를 분석하여 의료법 위반 여부를 판별"""
        result = AnalysisResult(
            response_text=response_text,
            guideline_version=self._guideline_version,
        )

        # 1) 의료 컨텍스트 감지
        result.is_medical_context = self._detect_medical_context(response_text)

        # 2) violation_rules.json + guidelines 병합 규칙 검사 (config.py 브릿지)
        for rule_id, rule in self.rules.items():
            violations = self._check_rule(rule_id, rule, response_text)
            result.violations.extend(violations)

        # 3) 가이드라인 prohibited_rules의 examples 기반 직접 매칭
        prohibited_violations = self._check_prohibited_examples(response_text)
        result.violations.extend(prohibited_violations)

        # 4) gray_zone 위험 표현 검사
        gray_violations = self._check_gray_zone(response_text)
        result.violations.extend(gray_violations)

        # 5) 응급 키워드 검사
        if self._emergency_keywords:
            emergency_violations = self._check_emergency_keywords(response_text)
            result.violations.extend(emergency_violations)

        # 6) 면책조항 확인 (의료 맥락인 경우)
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

        # 7) 필수 고정 문구 확인
        result.has_top_notice = self._check_top_notice(response_text)
        result.has_bottom_notice = self._check_bottom_notice(response_text)

        # 8) 중복 위반 제거 (같은 rule_id + 같은 matched_text)
        result.violations = self._deduplicate(result.violations)

        # 9) 준수 점수 계산
        result.compliance_score = self._calculate_score(result.violations)

        # 10) 요약 생성
        result.summary = self._generate_summary(result)

        return result

    # ─────────────────────────────────────────
    # 의료 컨텍스트 감지
    # ─────────────────────────────────────────
    def _detect_medical_context(self, text: str) -> bool:
        count = sum(1 for kw in self.MEDICAL_CONTEXT_KEYWORDS if kw in text)
        return count >= 2

    # ─────────────────────────────────────────
    # violation_rules 기반 검사 (레거시 + 가이드라인 병합)
    # ─────────────────────────────────────────
    def _check_rule(self, rule_id: str, rule: dict, text: str) -> list:
        violations = []
        if rule_id == "disclaimer_missing":
            return violations

        # 공통 필드 안전 추출
        r_name = rule.get("name", rule_id)
        r_law = rule.get("law", "")
        r_severity = rule.get("severity", "MEDIUM")
        r_desc = rule.get("description", "")
        r_score = SEVERITY_SCORES.get(r_severity, 40)

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
                        rule_name=r_name,
                        law=r_law,
                        severity=r_severity,
                        severity_score=r_score,
                        description=r_desc,
                        matched_text=matched,
                        match_type="pattern",
                        context=f"...{context}...",
                    ))
            except re.error:
                continue

        # 키워드 매칭
        for keyword in rule.get("keywords", []):
            if keyword in text:
                idx = text.find(keyword)
                if idx < 0:
                    continue
                start = max(0, idx - 30)
                end = min(len(text), idx + len(keyword) + 30)
                context = text[start:end]
                violations.append(ViolationMatch(
                    rule_id=rule_id,
                    rule_name=r_name,
                    law=r_law,
                    severity=r_severity,
                    severity_score=r_score,
                    description=r_desc,
                    matched_text=keyword,
                    match_type="keyword",
                    context=f"...{context}...",
                ))

        return violations

    # ─────────────────────────────────────────
    # 가이드라인 prohibited_rules examples 직접 매칭
    # ─────────────────────────────────────────
    def _check_prohibited_examples(self, text: str) -> list:
        """prohibited_rules의 examples에서 플레이스홀더 제거 후 키프레이즈 매칭"""
        violations = []
        for rule in self._prohibited_rules:
            rule_id = rule.get("id", "")
            examples = rule.get("examples", [])
            severity = rule.get("severity", "HIGH")
            law = rule.get("law", "")
            category = rule.get("category", rule_id)
            desc = rule.get("description", "")

            for ex in examples:
                # 플레이스홀더(OO, △△) 제거, 앞뒤 공백 정리
                clean = ex.replace("OO", "").replace("△△", "").replace("  ", " ").strip()
                # 핵심 키프레이즈 추출: 5자 이상인 연속 구문
                key_phrases = [p.strip() for p in clean.split("/") if len(p.strip()) >= 4]
                if not key_phrases and len(clean) >= 4:
                    key_phrases = [clean.rstrip('.')]

                for phrase in key_phrases:
                    phrase_clean = phrase.rstrip('.')
                    if len(phrase_clean) < 4:
                        continue
                    if phrase_clean in text:
                        idx = text.find(phrase_clean)
                        start = max(0, idx - 30)
                        end = min(len(text), idx + len(phrase_clean) + 30)
                        violations.append(ViolationMatch(
                            rule_id=rule_id,
                            rule_name=category,
                            law=law,
                            severity=severity,
                            severity_score=SEVERITY_SCORES.get(severity, 40),
                            description=desc,
                            matched_text=phrase_clean,
                            match_type="prohibited_example",
                            context=f"...{text[start:end]}...",
                        ))
        return violations

    # ─────────────────────────────────────────
    # gray_zone 위험 표현 검사
    # ─────────────────────────────────────────
    def _check_gray_zone(self, text: str) -> list:
        """gray_zone_rules의 prohibited_examples 매칭 → 위반 + safe_expression 권고"""
        violations = []
        for gz in self._gray_zone_rules:
            gz_id = gz.get("id", "gray_zone")
            topic = gz.get("topic", "")
            dangerous = gz.get("dangerous_expression", "")
            safe = gz.get("safe_expression", "")
            prohibited_examples = gz.get("prohibited_examples", [])

            # 1) 위험 표현 자체 매칭
            if dangerous and len(dangerous) >= 3 and dangerous in text:
                idx = text.find(dangerous)
                start = max(0, idx - 30)
                end = min(len(text), idx + len(dangerous) + 30)
                violations.append(ViolationMatch(
                    rule_id=gz_id,
                    rule_name=f"회색지대: {topic}",
                    law="의료법 제27조",
                    severity="MEDIUM",
                    severity_score=SEVERITY_SCORES["MEDIUM"],
                    description=f"위험 표현 '{dangerous}' → 권고: '{safe}'",
                    matched_text=dangerous,
                    match_type="gray_zone",
                    context=f"...{text[start:end]}...",
                ))

            # 2) 금지 예시 매칭
            for ex in prohibited_examples:
                ex_clean = ex.replace("OO", "").replace("△△", "").replace("  ", " ").strip().rstrip('.')
                if len(ex_clean) < 5:
                    continue
                if ex_clean in text:
                    idx = text.find(ex_clean)
                    start = max(0, idx - 30)
                    end = min(len(text), idx + len(ex_clean) + 30)
                    violations.append(ViolationMatch(
                        rule_id=gz_id,
                        rule_name=f"회색지대: {topic}",
                        law="의료법 제27조",
                        severity="MEDIUM",
                        severity_score=SEVERITY_SCORES["MEDIUM"],
                        description=f"금지 표현 '{ex_clean}' → 권고: '{safe}'",
                        matched_text=ex_clean,
                        match_type="gray_zone",
                        context=f"...{text[start:end]}...",
                    ))
        return violations

    # ─────────────────────────────────────────
    # 면책조항 확인
    # ─────────────────────────────────────────
    def _check_disclaimer(self, text: str) -> bool:
        """면책조항 포함 여부 확인 (violation_rules + guidelines 병합)"""
        disclaimer_kws = self.rules.get("disclaimer_missing", {}).get(
            "disclaimer_keywords", []
        )
        all_kws = set(disclaimer_kws) | set(self._disclaimer_keywords)
        return any(kw in text for kw in all_kws)

    # ─────────────────────────────────────────
    # 응급 키워드 검사
    # ─────────────────────────────────────────
    def _check_emergency_keywords(self, text: str) -> list:
        violations = []
        has_emergency_guide = any(w in text for w in ["119", "응급실", "응급 의료"])
        for kw in self._emergency_keywords:
            if kw in text and not has_emergency_guide:
                idx = text.find(kw)
                start = max(0, idx - 30)
                end = min(len(text), idx + len(kw) + 30)
                violations.append(ViolationMatch(
                    rule_id="emergency_guidance",
                    rule_name="응급상황 안내 누락",
                    law="응급의료에 관한 법률",
                    severity="HIGH",
                    severity_score=SEVERITY_SCORES["HIGH"],
                    description=f"응급 키워드 '{kw}' 감지 후 119/응급실 안내 누락",
                    matched_text=kw,
                    match_type="keyword",
                    context=f"...{text[start:end]}...",
                ))
                break  # 응급 안내 누락은 한 번만 보고
        return violations

    # ─────────────────────────────────────────
    # 필수 고정 문구 확인
    # ─────────────────────────────────────────
    def _check_top_notice(self, text: str) -> bool:
        top = self._fixed_notices.get("top_disclaimer", "")
        if not top:
            return True
        # 핵심 구문 일부 포함 여부로 판단 (전체 일치는 너무 엄격)
        key_parts = ["건강정보", "교육 목적", "참고용", "의료행위를 하지 않"]
        return any(p in text for p in key_parts)

    def _check_bottom_notice(self, text: str) -> bool:
        bottom = self._fixed_notices.get("bottom_disclaimer", "")
        if not bottom:
            return True
        return bottom in text or "의료진과 상담" in text

    # ─────────────────────────────────────────
    # 중복 제거
    # ─────────────────────────────────────────
    def _deduplicate(self, violations: list) -> list:
        seen = set()
        result = []
        for v in violations:
            key = (v.rule_id, v.matched_text, v.match_type)
            if key not in seen:
                seen.add(key)
                result.append(v)
        return result

    # ─────────────────────────────────────────
    # 점수 계산
    # ─────────────────────────────────────────
    def _calculate_score(self, violations: list) -> float:
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

    # ─────────────────────────────────────────
    # 요약 생성
    # ─────────────────────────────────────────
    def _generate_summary(self, result: AnalysisResult) -> str:
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
        return f"{status} — 총 {result.violation_count}건 위반 ({', '.join(parts)}) [가이드라인 v{result.guideline_version}]"

"""
packages/medical_shared/compliance_rules — public API re-export

Consumers can import from this package directly:
  from packages.medical_shared.compliance_rules import ComplianceAnalyzer
or via the root shims (analyzer, guideline_loader, consultation_loader, config).
"""

from .analyzer import ComplianceAnalyzer, ViolationMatch, AnalysisResult
from .guideline_loader import (
    load_guidelines, save_guidelines, get_version, get_change_history,
    get_fixed_notices, get_prohibited_rules, get_allowed_rules,
    get_gray_zone_rules, get_emergency_keywords, get_disclaimer_check_keywords,
    build_gpt_system_prompt,
)
from .consultation_loader import load_checklists_raw, load_checklists_by_symptom
from .rules_config import (
    VIOLATION_RULES, SEVERITY_SCORES,
    reload_violation_rules, get_guideline_version,
    _load_violation_rules, _load_violation_rules_legacy,
)

__all__ = [
    'ComplianceAnalyzer', 'ViolationMatch', 'AnalysisResult',
    'load_guidelines', 'save_guidelines', 'get_version', 'get_change_history',
    'get_fixed_notices', 'get_prohibited_rules', 'get_allowed_rules',
    'get_gray_zone_rules', 'get_emergency_keywords', 'get_disclaimer_check_keywords',
    'build_gpt_system_prompt',
    'load_checklists_raw', 'load_checklists_by_symptom',
    'VIOLATION_RULES', 'SEVERITY_SCORES',
    'reload_violation_rules', 'get_guideline_version',
    '_load_violation_rules', '_load_violation_rules_legacy',
]

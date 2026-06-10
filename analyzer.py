"""
analyzer.py (루트 shim) — 4-B/B2
==================================
실제 구현은 packages/medical_shared/compliance_rules/analyzer.py 로 이동했다.
모듈 별칭 방식으로 sys.modules 에 등록해 런타임 패치 및 `import analyzer` 를
투명하게 지원한다.
"""
import sys as _sys
import importlib as _importlib

_impl = _importlib.import_module('packages.medical_shared.compliance_rules.analyzer')
_sys.modules['analyzer'] = _impl
_sys.modules[__name__] = _impl

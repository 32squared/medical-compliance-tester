# -*- coding: utf-8 -*-
"""등급별 질답 화면(/grades) — 라우트·권한·규칙 사전 API 의 재료를 확인한다."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_grades_route_and_permission():
    s = _src("proxy_server.py")
    assert "'/grades': 'grade_viewer.html'" in s
    perms = s[s.index("PAGE_PERMISSIONS = {"):]
    perms = perms[:perms.index("}")]
    assert re.search(r"'/grades':\s*'view_history'", perms)
    assert re.search(r"'/grade_viewer\.html':\s*'view_history'", perms)
    assert "path == '/api/eval-v3/rules'" in s          # perm_blocks 의 /api/eval-v3/ 보호 아래


def test_nav_has_grade_viewer():
    s = _src("app_nav.js")
    assert "href: '/grades'" in s and "'/grade_viewer.html': '/grades'" in s


def test_rule_names_have_viewer_fields():
    import gold_labels
    rules = gold_labels.rule_names()
    if not rules:                                        # 판정기 없는 환경이면 빈 dict 허용
        return
    r = rules.get("PV-05") or next(iter(rules.values()))
    assert set(r) >= {"title", "note", "method", "required", "level"}
    assert any(k.startswith("UV-") for k in rules) and any(k.startswith("LG-") for k in rules)


def test_viewer_html_uses_rules_and_history_api():
    s = _src("grade_viewer.html")
    assert "/api/eval-v3/rules" in s and "/api/history/" in s and "/api/eval-v3/runs" in s
    assert 'id="appNav"' in s and "/app_nav.js" in s

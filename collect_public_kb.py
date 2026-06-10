"""
공공 의료 출처 자동 수집기 — RAG KB Phase 2
출처: MFDS 의약품안전나라 + 응급의료포털(NEMC) + 공공데이터포털 KDCA OpenAPI
라이선스: 공공누리 1유형 (출처 표시 시 자유 사용)
모든 문서 status='active' 직접 적재 (의사 검수 면제 정책)

Fetch → Parse → 위반패턴 검사 → evidence_topic 자동 라벨링 → ingest

사용:
    python collect_public_kb.py                          # 3개 출처 전체 수집
    python collect_public_kb.py --source mfds            # MFDS만
    python collect_public_kb.py --source nemc --dry-run  # NEMC 미리보기
    python collect_public_kb.py --max-per-source 20      # 출처당 최대 20건
"""

import io
import os
import re
import sys
import json
import time
import hashlib
import logging
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any

# 한글 출력 보장
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 프로젝트 루트를 sys.path 에 추가
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
#  외부 라이브러리 임포트 (없으면 폴백 경고)
# ────────────────────────────────────────────────────────────

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    logger.error("[Collect] requests 없음 — pip install requests")

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False
    logger.error("[Collect] beautifulsoup4 없음 — pip install beautifulsoup4")

try:
    from markdownify import markdownify as _md_convert
    _HAS_MARKDOWNIFY = True
except ImportError:
    _HAS_MARKDOWNIFY = False
    logger.warning("[Collect] markdownify 없음 — html2text 폴백 시도")
    try:
        import html2text as _html2text_mod
        _HAS_HTML2TEXT = True
    except ImportError:
        _HAS_HTML2TEXT = False
        logger.warning("[Collect] html2text도 없음 — get_text 폴백 사용")


# ────────────────────────────────────────────────────────────
#  상수
# ────────────────────────────────────────────────────────────

_REQUEST_TIMEOUT = 30        # requests 타임아웃 (초)
_REQUEST_RETRY = 3           # 최대 재시도 횟수
_REQUEST_BACKOFF = 1.5       # 지수 백오프 배수
_RATE_LIMIT_SLEEP = 1.0      # 요청 사이 대기 시간 (초)
_DRY_RUN_PREVIEW = 5         # dry_run 미리보기 건수

# MFDS 의약품안전나라 안전성 서한 게시판
_MFDS_BASE = "https://nedrug.mfds.go.kr"
# JS 동적 로딩 → 실제 JSON API 엔드포인트 사용
_MFDS_PAGING_URL = _MFDS_BASE + "/pbp/CCBBB01/getItemPaging"
_MFDS_DETAIL_URL = _MFDS_BASE + "/pbp/CCBBB01/getItemDetail"

# 응급의료포털(E-Gen) 응급처치 가이드 — 실제 URL 구조 (2026년 기준)
# /nemc/first_aid_step.do 는 404 → /egen/ 하위로 변경됨
_NEMC_BASE = "https://www.e-gen.or.kr"

# 공공데이터포털 KDCA OpenAPI
_KDCA_API_BASE = "https://apis.data.go.kr/1790387"

# 국가건강정보포털 (health.kdca.go.kr)
# KDCA 산하 정적 HTML 사이트, 공공누리 1유형
# 2026년 기준 URL 구조:
#   목록: POST wisenutApiResult.do (Wisenut 검색엔진 JSON API)
#   상세: POST gnrlzHealthInfoView.do?cntnts_sn={N}
_HEALTH_KDCA_BASE = "https://health.kdca.go.kr"
_HEALTH_KDCA_SEARCH_API = (
    _HEALTH_KDCA_BASE
    + "/healthinfo/biz/health/unifiedSearch/wisenutApiResult.do"
)
_HEALTH_KDCA_VIEW_URL = (
    _HEALTH_KDCA_BASE
    + "/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do"
)

# KB source_id (마이그레이션 003/004에서 시드된 ID와 일치해야 함)
# kb_sources 테이블: 'mfds' / 'nemc' / 'kdca_api' / 'health_kdca'
_SOURCE_ID_MFDS = "mfds"
_SOURCE_ID_NEMC = "nemc"
_SOURCE_ID_KDCA = "kdca_api"
_SOURCE_ID_HEALTH_KDCA = "health_kdca"


# ────────────────────────────────────────────────────────────
#  42증상 목록 로드 (evidence_topic 라벨링용)
# ────────────────────────────────────────────────────────────

def _load_symptom_list() -> List[Dict]:
    """consultation_checklists.json 42증상 목록 로드 (consultation_loader 위임)."""
    import consultation_loader
    return consultation_loader.load_checklists_raw()


_SYMPTOM_LIST: List[Dict] = _load_symptom_list()
# 라벨링 캐시 (title → evidence_topic)
_TOPIC_CACHE: Dict[str, str] = {}


# ────────────────────────────────────────────────────────────
#  HTTP 세션 (재시도 + 타임아웃)
# ────────────────────────────────────────────────────────────

def _make_session() -> "requests.Session":
    """지수 백오프 재시도 세션 생성."""
    session = requests.Session()
    retry = Retry(
        total=_REQUEST_RETRY,
        backoff_factor=_REQUEST_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (compatible; MedComplianceBot/2.0; "
            "+https://github.com/medical-compliance-tester)"
        )
    })
    return session


# ────────────────────────────────────────────────────────────
#  HTML → Markdown 변환
# ────────────────────────────────────────────────────────────

def _html_to_markdown(html: str) -> str:
    """
    HTML 문자열을 Markdown으로 변환.
    우선순위: markdownify > html2text > BeautifulSoup get_text
    """
    if not html:
        return ""

    if _HAS_MARKDOWNIFY:
        try:
            md = _md_convert(html, heading_style="ATX", strip=["script", "style"])
            return _clean_markdown(md)
        except Exception as e:
            logger.debug("[Collect] markdownify 오류: %s", e)

    if not _HAS_MARKDOWNIFY and _HAS_HTML2TEXT:
        try:
            h = _html2text_mod.HTML2Text()
            h.ignore_links = False
            h.ignore_images = True
            h.body_width = 0
            return _clean_markdown(h.handle(html))
        except Exception as e:
            logger.debug("[Collect] html2text 오류: %s", e)

    # 최후 폴백: BeautifulSoup get_text + 단순 구조 보존
    if _HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        # 헤더 변환
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            level = int(tag.name[1])
            tag.replace_with("#" * level + " " + tag.get_text() + "\n")
        # 단락/리스트 줄바꿈
        for tag in soup.find_all(["p", "li", "br"]):
            tag.insert_after("\n")
        return _clean_markdown(soup.get_text())

    return html  # 모두 실패 시 원문 반환


def _clean_markdown(text: str) -> str:
    """Markdown 텍스트 정리 (연속 빈줄 압축 등)."""
    # 3줄 이상 연속 빈줄을 2줄로 압축
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 줄 앞뒤 공백 제거
    lines = [line.rstrip() for line in text.split('\n')]
    return '\n'.join(lines).strip()


# ────────────────────────────────────────────────────────────
#  SHA-256 체크섬
# ────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ────────────────────────────────────────────────────────────
#  현재 시각 ISO 8601
# ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ════════════════════════════════════════════════════════════
#  출처 1: MFDS 의약품안전나라 안전성 서한
# ════════════════════════════════════════════════════════════

def fetch_mfds_safety_letters(limit: int = 100) -> List[Dict]:
    """
    MFDS 의약품안전나라 안전성 서한 게시판 수집.
    목록: /pbp/CCBBB01/getItemPaging (JSON API, JS 동적 로딩 방식)
    상세: /pbp/CCBBB01/getItemDetail?itemSeq=XXX

    Cloud Run NAT 고정 IP 환경에서 nedrug.mfds.go.kr의 JSON API
    (/pbp/CCBBB01/getItemPaging)가 IP 화이트리스트 미등록으로 타임아웃 발생.
    # TODO: MFDS는 NAT IP 화이트리스트 대기 — 등록 완료 후 재활성화 필요.
    해당 경우 빈 리스트 반환 + WARNING 로그 출력 (ERROR 아님).

    Returns:
        [{'title', 'content_md', 'source_url', 'published_at', 'source_checksum'}]
    """
    if not _HAS_REQUESTS or not _HAS_BS4:
        logger.error("[MFDS] requests/bs4 없음 — 수집 불가")
        return []

    session = _make_session()
    results = []
    fetched_at = _now_iso()
    page_size = min(limit, 20)

    page = 1
    while len(results) < limit:
        params = {
            "page": page,
            "listSize": page_size,
            "boardCode": "A0035",   # 안전성 서한 게시판 코드
        }
        try:
            resp = session.get(
                _MFDS_PAGING_URL, params=params, timeout=_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except Exception as e:
            err_str = str(e).lower()
            # 타임아웃 또는 연결 거부 → NAT IP 미화이트리스트 가능성
            if any(kw in err_str for kw in ("timeout", "timed out", "connection", "refused")):
                logger.warning(
                    "[MFDS] 목록 API 접근 불가 (NAT IP 화이트리스트 대기 중): %s "
                    "— 빈 결과 반환. MFDS NAT IP 등록 완료 후 재실행 필요.",
                    e,
                )
                return []
            logger.warning("[MFDS] 목록 API 페이지 %d 오류: %s", page, e)
            break

        # JSON 응답 파싱
        try:
            data = resp.json()
        except Exception:
            logger.warning("[MFDS] 목록 JSON 파싱 실패 (page=%d)", page)
            break

        # 표준 응답 구조: {list: [...], totalCount: N}
        items_raw = data if isinstance(data, list) else (
            data.get("list") or data.get("items") or data.get("data") or []
        )
        if not items_raw:
            logger.info("[MFDS] 페이지 %d 데이터 없음 — 수집 종료", page)
            break

        page_items = 0
        for item in items_raw:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue

            # 공통 필드명 후보
            item_seq = (
                item.get("itemSeq") or item.get("seq") or
                item.get("boardSeq") or item.get("no") or ""
            )
            title_text = (
                item.get("itemName") or item.get("title") or
                item.get("boardTitle") or item.get("subject") or ""
            ).strip()
            published_at = (
                item.get("changeDate") or item.get("regDate") or
                item.get("boardDate") or item.get("date") or ""
            )

            if not title_text:
                continue

            # 상세 URL 구성
            if item_seq:
                detail_url = f"{_MFDS_DETAIL_URL}?itemSeq={item_seq}"
            else:
                detail_url = _MFDS_BASE + "/pbp/CCBBB01"

            time.sleep(_RATE_LIMIT_SLEEP)

            # 상세 페이지 fetch (HTML)
            try:
                detail_resp = session.get(detail_url, timeout=_REQUEST_TIMEOUT)
                detail_resp.raise_for_status()
                detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                body_el = (
                    detail_soup.select_one("div.view_cont")
                    or detail_soup.select_one("div.board_view")
                    or detail_soup.select_one("div#contentsWrap")
                    or detail_soup.select_one("div.cont_area")
                    or detail_soup.select_one("main")
                )
                body_html = str(body_el) if body_el else detail_resp.text
                content_md = _html_to_markdown(body_html)
            except Exception as e:
                # 상세 페이지 실패 시 목록 필드 기반 요약 사용
                logger.debug("[MFDS] 상세 페이지 오류 (%s): %s — 목록 요약 사용", detail_url, e)
                summary = item.get("content") or item.get("summary") or title_text
                content_md = f"**{title_text}**\n\n{summary}"

            if not content_md.strip():
                logger.debug("[MFDS] 빈 본문 스킵: %s", title_text)
                continue

            # 출처 표기 추가 (공공누리 1유형 준수)
            content_md = (
                f"# {title_text}\n\n"
                f"> 출처: 식품의약품안전처 의약품안전나라 ({detail_url})\n\n"
                + content_md
            )
            checksum = _sha256(content_md)

            results.append({
                "title": title_text,
                "content_md": content_md,
                "source_url": detail_url,
                "published_at": published_at,
                "source_checksum": checksum,
                "source_fetched_at": fetched_at,
            })
            page_items += 1

        if page_items == 0 or len(items_raw) < page_size:
            break
        page += 1
        time.sleep(_RATE_LIMIT_SLEEP)

    logger.info("[MFDS] 수집 완료: %d건", len(results))
    return results


# ════════════════════════════════════════════════════════════
#  출처 2: 응급의료포털(NEMC) 응급처치 가이드
# ════════════════════════════════════════════════════════════

# 응급의료포털(E-Gen) 실제 URL 구조 (2026년 기준 사이트맵 확인)
# /nemc/first_aid_step.do 는 404 → /egen/ 하위 도메인으로 변경됨
_NEMC_TOPICS = [
    # 기본응급처치 (first_aid_basics.do)
    {"key": "cpr_aed",          "name": "심폐소생술 및 자동심장충격기", "url": "/egen/first_aid_basics.do?contentsno=16"},
    {"key": "adult_cpr",        "name": "성인 심폐소생술",              "url": "/egen/first_aid_basics.do?contentsno=17"},
    {"key": "child_cpr",        "name": "소아 심폐소생술",              "url": "/egen/first_aid_basics.do?contentsno=18"},
    {"key": "airway_obstruct",  "name": "성인·소아 기도폐쇄",          "url": "/egen/first_aid_basics.do?contentsno=19"},
    {"key": "infant_airway",    "name": "영아 기도폐쇄",               "url": "/egen/first_aid_basics.do?contentsno=20"},
    {"key": "dressing",         "name": "드레싱 및 붕대이용법",         "url": "/egen/first_aid_basics.do?contentsno=21"},
    {"key": "transport",        "name": "환자를 옮기는 법",             "url": "/egen/first_aid_basics.do?contentsno=22"},
    # 응급상황 개요 (first_aid.do)
    {"key": "emergency_action", "name": "응급상황시 행동원칙",          "url": "/egen/first_aid.do?contentsno=11"},
    {"key": "emergency_system", "name": "응급의료체계",                 "url": "/egen/first_aid.do?contentsno=12"},
    # 여행 응급상황 (emergency_situation.do)
    {"key": "travel_emergency", "name": "여행중 일어날 수 있는 응급상황", "url": "/egen/emergency_situation.do?contentsno=13"},
    {"key": "flight_emergency", "name": "항공 여행 시 응급상황",         "url": "/egen/emergency_situation.do?contentsno=14"},
    # 상황별응급처치
    {"key": "bite_sting",       "name": "동물·곤충에 물렸을 때",        "url": "/egen/bitten.do"},
    # 가정 내 응급처치 (first_aid_home.do)
    {"key": "minor_wound",      "name": "얕은 손상",                    "url": "/egen/first_aid_home.do?contentsno=92"},
    {"key": "urticaria",        "name": "두드러기",                     "url": "/egen/first_aid_home.do?contentsno=93"},
    {"key": "sprain",           "name": "단순 염좌",                    "url": "/egen/first_aid_home.do?contentsno=94"},
    {"key": "eye_injury",       "name": "안과 응급처치",                "url": "/egen/first_aid_home.do?contentsno=95"},
    {"key": "minor_burn",       "name": "경미한 화상",                  "url": "/egen/first_aid_home.do?contentsno=96"},
    {"key": "child_fever",      "name": "소아 발열",                    "url": "/egen/first_aid_home.do?contentsno=97"},
    {"key": "mild_abdom",       "name": "가벼운 복통",                  "url": "/egen/first_aid_home.do?contentsno=98"},
]


def fetch_nemc_first_aid() -> List[Dict]:
    """
    응급의료포털(E-Gen) 응급처치 가이드 수집.
    실제 URL 구조 (2026년 기준):
      - /egen/first_aid_basics.do?contentsno=16~22  (기본응급처치)
      - /egen/first_aid.do?contentsno=11~12         (응급처치 개요)
      - /egen/emergency_situation.do?contentsno=13~14 (여행 응급상황)
      - /egen/bitten.do                             (상황별응급처치)
      - /egen/first_aid_home.do?contentsno=92~98    (가정 내 응급처치)

    Returns:
        [{'title', 'content_md', 'source_url', 'source_checksum', 'source_fetched_at'}]
    """
    if not _HAS_REQUESTS or not _HAS_BS4:
        logger.error("[NEMC] requests/bs4 없음 — 수집 불가")
        return []

    session = _make_session()
    results = []
    fetched_at = _now_iso()

    for topic in _NEMC_TOPICS:
        url = _NEMC_BASE + topic["url"]
        time.sleep(_RATE_LIMIT_SLEEP)

        try:
            resp = session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("[NEMC] 페이지 오류 (%s): %s", topic["name"], e)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # 응급처치 본문 영역 추출 (E-Gen 구조)
        body_el = (
            soup.select_one("div.cont_area")
            or soup.select_one("div.contents_area")
            or soup.select_one("div.first_aid_area")
            or soup.select_one("div#contentsArea")
            or soup.select_one("div.sub_cont")
            or soup.select_one("div#contents")
            or soup.select_one("main")
        )

        if not body_el:
            body_el = soup.find("body")

        # 불필요한 요소 제거 (네비게이션, 푸터, 스크립트 등)
        for unwanted in (body_el or soup).select(
            "header, footer, nav, .gnb, .lnb, .footer, .side_area, "
            ".breadcrumb, .btn_wrap, script, style, .top-button"
        ):
            unwanted.decompose()

        body_html = str(body_el) if body_el else resp.text
        content_md = _html_to_markdown(body_html)

        if not content_md.strip():
            logger.debug("[NEMC] 빈 본문 스킵: %s", topic["name"])
            continue

        # 출처 표기 추가
        content_md = (
            f"# 응급처치 가이드: {topic['name']}\n\n"
            f"> 출처: 응급의료포털 E-Gen ({url})\n\n"
            + content_md
        )
        checksum = _sha256(content_md)
        title = f"응급처치 가이드 - {topic['name']}"

        results.append({
            "title": title,
            "content_md": content_md,
            "source_url": url,
            "source_checksum": checksum,
            "source_fetched_at": fetched_at,
        })
        logger.info("[NEMC] 수집: %s → %d bytes", topic["name"], len(content_md))

    logger.info("[NEMC] 수집 완료: %d건", len(results))
    return results


# ════════════════════════════════════════════════════════════
#  출처 3: 공공데이터포털 KDCA OpenAPI
# ════════════════════════════════════════════════════════════

def fetch_kdca_openapi(api_key: str, limit: int = 100) -> List[Dict]:
    """
    공공데이터포털 KDCA OpenAPI — 감염병 정보 + 예방접종 가이드.
    환경변수 KDCA_API_KEY 없으면 빈 리스트 반환 + 경고.

    Returns:
        [{'title', 'content_md', 'source_url', 'source_checksum', 'source_fetched_at'}]
    """
    if not api_key:
        logger.warning("[KDCA] KDCA_API_KEY 없음 — KDCA 출처 스킵")
        return []

    if not _HAS_REQUESTS:
        logger.error("[KDCA] requests 없음 — 수집 불가")
        return []

    session = _make_session()
    results = []
    fetched_at = _now_iso()

    # KDCA 감염병 목록 API (예: 법정감염병 목록)
    # 공공데이터포털 KDCA 오픈API 엔드포인트
    endpoints = [
        {
            "name": "감염병 정보",
            "url": f"{_KDCA_API_BASE}/infectdisease/infectDiseaseStat",
            "params": {
                "serviceKey": api_key,
                "pageNo": 1,
                "numOfRows": min(limit, 100),
                "returnType": "json",
            },
            "item_key": "items",
            "title_field": "diseaseName",
            "content_fields": ["symptomsAndSigns", "incubationPeriod",
                               "transmissionPath", "treatmentMethod", "preventionMethod"],
        },
        {
            "name": "예방접종 가이드",
            "url": f"{_KDCA_API_BASE}/vaccInfo/vaccInfoList",
            "params": {
                "serviceKey": api_key,
                "pageNo": 1,
                "numOfRows": min(limit, 100),
                "returnType": "json",
            },
            "item_key": "items",
            "title_field": "vaccName",
            "content_fields": ["vaccTarget", "vaccSchedule", "vaccEffect",
                               "vaccSideEffect", "vaccContraindication"],
        },
    ]

    for ep in endpoints:
        if len(results) >= limit:
            break

        time.sleep(_RATE_LIMIT_SLEEP)
        try:
            resp = session.get(ep["url"], params=ep["params"], timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("[KDCA] API 호출 오류 (%s): %s", ep["name"], e)
            continue

        try:
            data = resp.json()
        except Exception:
            logger.warning("[KDCA] JSON 파싱 실패 (%s)", ep["name"])
            continue

        # 응답 구조 탐색 (공공데이터포털 표준 구조)
        items = []
        try:
            # 표준: response.body.items.item
            body = data.get("response", data).get("body", {})
            raw_items = body.get(ep["item_key"], {})
            if isinstance(raw_items, dict):
                items = raw_items.get("item", [])
            elif isinstance(raw_items, list):
                items = raw_items
        except (AttributeError, TypeError):
            logger.warning("[KDCA] 응답 구조 파싱 실패 (%s)", ep["name"])
            continue

        if not isinstance(items, list):
            items = [items] if items else []

        for item in items:
            if len(results) >= limit:
                break

            if not isinstance(item, dict):
                continue

            title_raw = item.get(ep["title_field"], "")
            if not title_raw:
                continue

            title = f"[KDCA] {ep['name']}: {title_raw}"

            # 컨텐츠 필드 조합 → Markdown
            md_lines = [f"# {title}\n", f"> 출처: 공공데이터포털 KDCA ({ep['url']})\n"]
            for field in ep["content_fields"]:
                val = item.get(field, "")
                if val:
                    field_label = {
                        "symptomsAndSigns": "증상 및 징후",
                        "incubationPeriod": "잠복기",
                        "transmissionPath": "전파 경로",
                        "treatmentMethod": "치료 방법",
                        "preventionMethod": "예방 방법",
                        "vaccTarget": "접종 대상",
                        "vaccSchedule": "접종 일정",
                        "vaccEffect": "예방 효과",
                        "vaccSideEffect": "이상반응",
                        "vaccContraindication": "금기 사항",
                    }.get(field, field)
                    md_lines.append(f"\n## {field_label}\n\n{val}\n")

            content_md = "\n".join(md_lines).strip()
            if not content_md:
                continue

            checksum = _sha256(content_md)
            source_url = ep["url"] + f"?name={requests.utils.quote(title_raw)}"

            results.append({
                "title": title,
                "content_md": content_md,
                "source_url": source_url,
                "source_checksum": checksum,
                "source_fetched_at": fetched_at,
            })

        time.sleep(_RATE_LIMIT_SLEEP)

    logger.info("[KDCA] 수집 완료: %d건", len(results))
    return results


# ════════════════════════════════════════════════════════════
#  출처 4: 국가건강정보포털 (health.kdca.go.kr)
# ════════════════════════════════════════════════════════════

# 국가건강정보포털 Wisenut 검색 카테고리 (lclasSn)
# 0=전체, 1=건강문제, 2=치료방법, 3=검사방법, 4=생활습관 관리
_HEALTH_KDCA_CATEGORIES = [
    {"lclasSn": "1", "name": "건강문제"},
    {"lclasSn": "2", "name": "치료방법"},
    {"lclasSn": "3", "name": "검사방법"},
    {"lclasSn": "4", "name": "생활습관 관리"},
]

# 검색어 목록 — 42증상 + 주요 만성질환 키워드 (페이지당 50건 기준)
_HEALTH_KDCA_KEYWORDS = [
    "건강", "증상", "질환", "치료", "예방", "검사",
    "당뇨", "고혈압", "심장", "뇌졸중", "암", "폐",
    "간", "신장", "위", "장", "뼈", "관절",
    "피부", "눈", "귀", "코", "목", "치아",
    "두통", "발열", "기침", "호흡", "복통", "설사",
    "알레르기", "정신", "비만", "고지혈증", "갑상선", "빈혈",
]


def fetch_health_kdca(limit: int = 200) -> List[Dict]:
    """
    국가건강정보포털 (health.kdca.go.kr) 건강정보 수집.
    라이선스: 공공누리 1유형 (출처 표시 시 자유 사용)

    수집 방식:
      1. Wisenut 검색 API (POST wisenutApiResult.do) 로 CNTNTS_SN 목록 수집
         - 키워드별 최대 50건 × 다수 키워드 → 중복 제거
      2. 상세 페이지 (POST gnrlzHealthInfoView.do, cntnts_sn={N}) HTML 파싱
         - BeautifulSoup으로 #print-content 또는 contentsDiv1~6 추출

    Args:
        limit: 최대 수집 건수 (기본 200)

    Returns:
        [{'title', 'content_md', 'source_url', 'published_at',
          'source_checksum', 'source_fetched_at'}]
    """
    if not _HAS_REQUESTS or not _HAS_BS4:
        logger.error("[HealthKDCA] requests/bs4 없음 — 수집 불가")
        return []

    session = _make_session()
    # 국가건강정보포털은 한글 Referer 필요
    session.headers.update({
        "Referer": (
            _HEALTH_KDCA_BASE
            + "/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoMain.do"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
    })

    fetched_at = _now_iso()
    results: List[Dict] = []
    seen_sns: set = set()  # 중복 CNTNTS_SN 방지

    # ── 1단계: Wisenut API로 CNTNTS_SN 목록 수집 ──────────────
    candidate_sns: List[Dict] = []  # [{'sn': str, 'title': str, 'summary': str}]

    for kw in _HEALTH_KDCA_KEYWORDS:
        if len(candidate_sns) >= limit * 3:
            break
        time.sleep(_RATE_LIMIT_SLEEP)
        try:
            resp = session.post(
                _HEALTH_KDCA_SEARCH_API,
                data={
                    "query": kw,
                    "collection": "info",
                    "listCount": "50",
                    "useSynonym": "Y",
                    "useDefaultSynonym": "Y",
                },
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("[HealthKDCA] 검색 API 오류 (키워드=%s): %s", kw, e)
            continue

        try:
            doc_set = (
                data["SearchQueryResult"]["Collection"][0]["DocumentSet"]
            )
            docs = doc_set.get("Document", [])
            if not isinstance(docs, list):
                docs = [docs] if docs else []
        except (KeyError, IndexError, TypeError) as e:
            logger.debug("[HealthKDCA] 검색 응답 파싱 오류 (키워드=%s): %s", kw, e)
            continue

        new_cnt = 0
        for doc in docs:
            field = doc.get("Field", {})
            sn = field.get("CNTNTS_SN", "").strip()
            if not sn or sn in seen_sns:
                continue
            # CNTNTS_STTUS_CODE == 'D' 는 비공개/삭제 상태 — 스킵
            if field.get("CNTNTS_STTUS_CODE", "") == "D":
                # D는 실제로 '공개' 상태 코드임을 현장 확인 후 유지
                pass
            title_raw = field.get("CNTNTS_SJ", "").strip()
            # Wisenut 하이라이트 태그 제거 (<<!HS>..<!HE>>)
            title_raw = re.sub(r"<!H[SE]>", "", title_raw).strip()
            summary = re.sub(
                r"<!H[SE]>", "",
                field.get("CNTNTS_CL_CN", "") or "",
            ).strip()
            # 파이프 구분자 제거
            summary = re.sub(r"\|+", " ", summary).strip()
            pub_raw = field.get("SYS_UPDT_DT", "") or field.get("DATE", "")

            seen_sns.add(sn)
            candidate_sns.append({
                "sn": sn,
                "title": title_raw,
                "summary": summary,
                "published_at": pub_raw[:10] if pub_raw else "",
            })
            new_cnt += 1

        logger.debug(
            "[HealthKDCA] 키워드=%r → %d건 신규 (누적 %d건)",
            kw, new_cnt, len(candidate_sns),
        )

    logger.info(
        "[HealthKDCA] 후보 %d건 수집 → 상세 페이지 %d건 fetch 예정",
        len(candidate_sns), min(len(candidate_sns), limit),
    )

    # ── 2단계: 상세 페이지 fetch + 본문 추출 ──────────────────
    for cand in candidate_sns[:limit]:
        if len(results) >= limit:
            break

        sn = cand["sn"]
        title = cand["title"]
        detail_url = f"{_HEALTH_KDCA_VIEW_URL}?cntnts_sn={sn}"
        time.sleep(_RATE_LIMIT_SLEEP)

        try:
            resp = session.post(
                _HEALTH_KDCA_VIEW_URL,
                data={"cntnts_sn": sn},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            logger.warning(
                "[HealthKDCA] 상세 페이지 오류 (sn=%s, title=%s): %s",
                sn, title, e,
            )
            continue

        # 제목 보정: <title> 태그에서 추출 (Wisenut 값보다 정확)
        title_tag = soup.find("title")
        if title_tag:
            page_title = title_tag.get_text().split("|")[0].strip()
            if page_title and len(page_title) > 1:
                title = page_title

        # 본문 영역 추출 우선순위:
        #   1) #print-content (전체 본문 포함, 인쇄용 div)
        #   2) contentsDiv1~6 (섹션별 본문 탭)
        #   3) div.contents-Div
        body_el = soup.find(id="print-content")

        if not body_el:
            # contentsDiv1~6 합치기
            parts = []
            for i in range(1, 7):
                el = soup.find(id=f"contentsDiv{i}")
                if el:
                    parts.append(el)
            if parts:
                # 첫 번째를 base로 나머지 append
                body_el = parts[0]
                for part in parts[1:]:
                    body_el.append(part)

        if not body_el:
            body_el = soup.select_one("div.contents-Div")

        if not body_el:
            logger.debug(
                "[HealthKDCA] 본문 영역 없음 (sn=%s, title=%s) — 요약으로 폴백",
                sn, title,
            )
            if cand["summary"] and len(cand["summary"]) >= 200:
                content_md = (
                    f"# {title}\n\n"
                    f"> 출처: 국가건강정보포털 ({detail_url})\n\n"
                    + cand["summary"]
                )
            else:
                continue
        else:
            # 불필요한 요소 제거
            for unwanted in body_el.select(
                "script, style, .btn_wrap, .top-button, "
                "header, footer, nav, .gnb, .lnb, .side_area, .breadcrumb"
            ):
                unwanted.decompose()

            body_html = str(body_el)
            content_md = _html_to_markdown(body_html)

        if not content_md or not content_md.strip():
            continue

        # 최소 본문 길이 검사 (200자 미만 스킵)
        content_text = re.sub(r"[#>\s\-\*]", "", content_md)
        if len(content_text) < 200:
            logger.debug(
                "[HealthKDCA] 본문 부족 스킵 (sn=%s, len=%d): %s",
                sn, len(content_text), title,
            )
            continue

        # 출처 표기 추가 (공공누리 1유형 준수)
        content_md = (
            f"# {title}\n\n"
            f"> 출처: 질병관리청 국가건강정보포털 ({detail_url})\n\n"
            + content_md
        )
        checksum = _sha256(content_md)

        results.append({
            "title": title,
            "content_md": content_md,
            "source_url": detail_url,
            "published_at": cand["published_at"],
            "source_checksum": checksum,
            "source_fetched_at": fetched_at,
        })
        logger.info(
            "[HealthKDCA] 수집: sn=%s, title=%s → %d bytes",
            sn, title, len(content_md),
        )

    logger.info("[HealthKDCA] 수집 완료: %d건", len(results))
    return results


# ════════════════════════════════════════════════════════════
#  evidence_topic 자동 라벨링
# ════════════════════════════════════════════════════════════

def label_evidence_topic(text: str, title: str = "") -> str:
    """
    GPT-5-mini로 evidence_topic 자동 라벨링.
    42증상 매칭: 제목 기반 룰 우선 → 매칭 안 되면 GPT 호출.

    Args:
        text:  문서 본문 (처음 500자만 사용)
        title: 문서 제목 (캐시 키 + 룰 기반 매칭 우선)

    Returns:
        evidence_topic 문자열 (예: 'fever', 'chest_pain', 'general')
    """
    # 캐시 확인
    cache_key = title.strip()
    if cache_key in _TOPIC_CACHE:
        return _TOPIC_CACHE[cache_key]

    # 1단계: 제목/본문 키워드 기반 룰 매칭 (GPT 비용 절감)
    combined = (title + " " + text[:300]).lower()
    for symptom in _SYMPTOM_LIST:
        key = symptom.get("symptom_key", "")
        name = symptom.get("symptom_name", "")
        detail = symptom.get("detail", "")
        # 한글 이름 또는 상세 설명 키워드 포함 여부 확인
        keywords_to_check = [name] + detail.split(",")
        for kw in keywords_to_check:
            kw = kw.strip()
            if kw and kw in combined:
                _TOPIC_CACHE[cache_key] = key
                return key

    # 2단계: GPT-5-mini 호출 (룰 미매칭 시)
    if not os.environ.get("OPENAI_API_KEY"):
        _TOPIC_CACHE[cache_key] = "general"
        return "general"

    try:
        from llm_router import get_fallback_provider

        symptom_names = ", ".join(
            f"{s['symptom_key']}({s['symptom_name']})"
            for s in _SYMPTOM_LIST
        )
        system_prompt = (
            "당신은 의료 문서 분류 전문가입니다. "
            "다음 42증상 목록 중 가장 가까운 symptom_key 1개를 반환하라. "
            "목록에 없으면 'general'을 반환하라. "
            "오직 symptom_key 단어만 반환 (설명 없음).\n"
            f"증상 목록: {symptom_names}"
        )
        user_prompt = (
            f"문서 제목: {title}\n\n"
            f"문서 내용 (앞부분): {text[:500]}"
        )

        provider = get_fallback_provider()
        full_response = ""
        for chunk in provider.stream_chat(
            system=system_prompt,
            user=user_prompt,
            max_tokens=20,
            temperature=0.0,
        ):
            if chunk.get("type") == "GENERATION":
                full_response += chunk.get("text", "")
            elif chunk.get("type") == "STOP":
                break

        topic = full_response.strip().split()[0] if full_response.strip() else "general"
        # 유효한 symptom_key인지 검증
        valid_keys = {s["symptom_key"] for s in _SYMPTOM_LIST} | {"general"}
        if topic not in valid_keys:
            topic = "general"

        _TOPIC_CACHE[cache_key] = topic
        return topic

    except Exception as e:
        logger.warning("[Collect] GPT 라벨링 실패: %s", e)
        _TOPIC_CACHE[cache_key] = "general"
        return "general"


# ════════════════════════════════════════════════════════════
#  위반패턴 사전검사
# ════════════════════════════════════════════════════════════

# 공공 출처 source_id 집합 — 정보성 콘텐츠로 간주하여 KB 콘텐츠 컨텍스트 적용
_PUBLIC_SOURCES = {"health_kdca", "nemc", "mfds", "kdca_api", "consultation_seed", "guideline_internal"}

# KB 콘텐츠 컨텍스트: 정보성 문서에 게재 부적합한 패턴만 차단
# (진단·처방·검사 지시·면책조항 누락 등 환자 응답 가드레일 제외)
KB_CONTENT_VIOLATION_CATEGORIES = {
    "prescription",         # 특정 약 복용 지시 ("○○○을 복용하세요")
    "misleading_ad",        # 허위/과대 효능 ("100% 완치", "기적의 치료법")
    # emergency_guidance 는 환자 응답 전용 가드레일.
    # KB 문서 자체가 심정지·발열 응급처치 지침을 담고 있으므로
    # 정보성 콘텐츠(consultation_seed, nemc 등) 적재 시 적용하지 않음.
}

# 환자 응답 컨텍스트: 모든 가드레일 적용 (기존 동작)
PATIENT_RESPONSE_VIOLATION_CATEGORIES = {
    "diagnosis",
    "prescription",
    "treatment",
    "misleading_ad",
    "emergency_guidance",
    "gray_zone",
    "disclaimer_missing",
    "menopause_definitive",
    "antibiotic_guidance",
    "phr_self_negation",
    "persona_violation",
    "medical_directive",
}

# ── Option B: prescription 카테고리 내 KB-safe 완화 ───────────────────────────
#
# 검사 설명 문서에서 "의사가 처방합니다", "복용합니다", "하루 3번" 등이
# 설명형(정보성)으로 사용될 때 false positive가 발생함.
#
# 원칙: KB 컨텍스트에서는 "명령형 지시 서술어"가 있을 때만 처방 위반으로 차단.
#       설명형 서술어(~합니다/~됩니다/~입니다)만 있으면 정보성으로 간주.
#
# 차단 유지 대상:
#   - "복용하세요", "드세요", "드십시오", "투여하세요" 등 직접 명령형
#   - "드시기 바랍니다", "복용 바랍니다" 등 우회 명령형
# 완화 대상 (KB-safe):
#   - "복용합니다", "투여합니다", "처방합니다", "사용합니다" 등 설명형
#   - "하루 3번", "식후 30분" 등 투약 빈도 정보 단독 언급
#   - "mg을", "밀리그램" 등 용량 수치 단독 언급

# 매칭 context 윈도우 (match 앞뒤로 살펴볼 문자 수)
_KB_SAFE_CONTEXT_WINDOW = 60

# KB 콘텐츠에서 prescription 위반을 확정짓는 명령형 지시 패턴
_KB_COMMAND_FORM_RE = re.compile(
    r"(?:"
    r"복용\s*하세요|복용하세요|"
    r"드세요|드십시오|드시기\s*바랍니다|드시면\s*됩니다|"
    r"먹으세요|먹으십시오|섭취하세요|"
    r"투여하세요|투여\s*하세요|주사하세요|맞으세요|"
    r"바르세요|붙이세요|넣으세요|"
    r"시작하세요|중단하세요|바꾸세요|변경하세요|조절하세요|"
    r"복용\s*바랍니다|투약\s*하십시오|복용\s*합시다|시작\s*합시다"
    r")"
)


def _is_prescription_kb_safe(text: str, match_start: int, match_end: int) -> bool:
    """
    prescription 위반 매칭이 KB 콘텐츠 컨텍스트에서 정보성(safe)인지 판별.

    판별 기준: match 전후 _KB_SAFE_CONTEXT_WINDOW 문자 범위 안에
              명령형 지시 서술어(_KB_COMMAND_FORM_RE)가 없으면 정보성으로 간주.

    Args:
        text:        전체 본문
        match_start: 위반 매칭 시작 위치
        match_end:   위반 매칭 종료 위치

    Returns:
        True  — KB-safe (차단 면제)
        False — 명령형 지시 확인됨 (차단 유지)
    """
    window_start = max(0, match_start - _KB_SAFE_CONTEXT_WINDOW)
    window_end = min(len(text), match_end + _KB_SAFE_CONTEXT_WINDOW)
    snippet = text[window_start:window_end]
    return not bool(_KB_COMMAND_FORM_RE.search(snippet))


def _check_categories(content_md: str, categories: set) -> List[str]:
    """
    지정된 카테고리 집합에 해당하는 위반 패턴만 검사.

    Args:
        content_md: 검사할 마크다운 본문
        categories: 적용할 rule_id 집합

    Returns:
        [] (위반 없음) 또는 위반 설명 문자열 리스트
    """
    try:
        from analyzer import ComplianceAnalyzer
        from config import VIOLATION_RULES

        # 지정 카테고리만 포함하는 규칙 서브셋으로 analyzer 인스턴스 생성
        filtered_rules = {k: v for k, v in VIOLATION_RULES.items() if k in categories}
        analyzer = ComplianceAnalyzer(rules=filtered_rules)
        result = analyzer.analyze(content_md)
        if result.violations:
            # analyze()가 categories 외 rule_id(예: disclaimer_missing)를
            # 하드코딩으로 추가할 수 있으므로 categories 기준으로 재필터링
            filtered_violations = [
                v for v in result.violations if v.rule_id in categories
            ]
            return [
                f"{v.rule_id}: {v.description} (severity={v.severity})"
                for v in filtered_violations
            ]
        return []
    except Exception as e:
        logger.warning("[Collect] 위반패턴 검사 오류: %s", e)
        return []  # 검사 실패 시 SKIP 안 함 (보수적)


def _check_categories_kb(content_md: str, categories: set) -> List[str]:
    """
    KB 콘텐츠 전용 카테고리 검사.
    _check_categories()와 동일하되, prescription 카테고리에 대해
    Option B KB-safe 완화(_is_prescription_kb_safe)를 적용.

    명령형 지시 서술어가 없는 prescription 매칭은 차단에서 제외.

    Args:
        content_md: 검사할 마크다운 본문
        categories: 적용할 rule_id 집합 (KB_CONTENT_VIOLATION_CATEGORIES)

    Returns:
        [] (위반 없음) 또는 위반 설명 문자열 리스트
    """
    try:
        from analyzer import ComplianceAnalyzer
        from config import VIOLATION_RULES

        filtered_rules = {k: v for k, v in VIOLATION_RULES.items() if k in categories}
        analyzer = ComplianceAnalyzer(rules=filtered_rules)
        result = analyzer.analyze(content_md)
        if not result.violations:
            return []

        final_violations = []
        for v in result.violations:
            if v.rule_id not in categories:
                continue

            # prescription 카테고리: KB-safe 완화 적용
            if v.rule_id == "prescription":
                # matched_text의 위치를 content_md에서 찾아 context 기반 판별
                idx = content_md.find(v.matched_text)
                if idx >= 0:
                    if _is_prescription_kb_safe(content_md, idx, idx + len(v.matched_text)):
                        logger.debug(
                            "[Collect] KB-safe 면제 (prescription, 설명형): %r",
                            v.matched_text[:60],
                        )
                        continue  # 정보성 표현 — 차단 제외
                # matched_text 위치 미발견 시 보수적으로 차단 유지

            final_violations.append(
                f"{v.rule_id}: {v.description} (severity={v.severity})"
            )

        return final_violations

    except Exception as e:
        logger.warning("[Collect] KB 위반패턴 검사 오류: %s", e)
        return []  # 검사 실패 시 SKIP 안 함 (보수적)


def precheck_violations(content_md: str, source_id: str = None) -> List[str]:
    """
    KB 콘텐츠 사전검사.
    공공 출처(health_kdca, nemc, mfds, kdca_api, consultation_seed, guideline_internal)는
    '정보성 콘텐츠'이므로 환자 응답 가드레일을 면제하고
    KB 게재 부적합 패턴만 검사 (처방 약 추천, 허위 효능, 응급 무시 등).

    [Option B 적용]
    공공 출처의 prescription 카테고리는 명령형 지시 서술어가 있을 때만 차단.
    "의사가 처방합니다", "복용합니다", "하루 3번 복용" 등 설명형 표현은 허용.

    Args:
        content_md: 검사할 마크다운 본문
        source_id: 출처 ID — 공공 출처면 'kb_content' 컨텍스트, 그 외는 'patient_response'
            - 공공 출처: KB_CONTENT_VIOLATION_CATEGORIES 적용 + Option B 완화
            - 비공공/None: PATIENT_RESPONSE_VIOLATION_CATEGORIES 적용 (기존 동작 유지)

    Returns:
        [] (위반 없음) 또는 위반 설명 문자열 리스트
    """
    if source_id in _PUBLIC_SOURCES:
        # 정보성 KB 콘텐츠 — 게재 부적합 패턴만 차단 (Option B 완화 포함)
        return _check_categories_kb(content_md, KB_CONTENT_VIOLATION_CATEGORIES)
    else:
        # 환자 응답 / 출처 미상 — 전체 가드레일 적용 (기존 동작 유지)
        return _check_categories(content_md, PATIENT_RESPONSE_VIOLATION_CATEGORIES)


# ════════════════════════════════════════════════════════════
#  통합 수집 + ingest
# ════════════════════════════════════════════════════════════

def collect_all(
    max_per_source: int = 100,
    dry_run: bool = False,
    sources: Optional[List[str]] = None,
) -> Dict:
    """
    3개 출처 통합 수집 + KB ingest.

    Args:
        max_per_source: 출처당 최대 수집 건수
        dry_run:        True면 DB INSERT 없이 샘플 5건 콘솔 미리보기
        sources:        수집할 출처 리스트 ['mfds','nemc','kdca'] (None이면 전체)

    Returns:
        {
          'fetched': int,
          'inserted': int,
          'skipped_dup': int,
          'skipped_violation': int,
          'errors': [str]
        }
    """
    if sources is None:
        sources = ["mfds", "nemc", "kdca", "health_kdca"]

    kdca_key = os.environ.get("KDCA_API_KEY", "")

    stats = {
        "fetched": 0,
        "inserted": 0,
        "skipped_dup": 0,
        "skipped_violation": 0,
        "errors": [],
    }

    # ── 수집 단계 ────────────────────────────────────────────
    all_items: List[Dict] = []

    if "mfds" in sources:
        logger.info("[Collect] MFDS 수집 시작 (max=%d)", max_per_source)
        try:
            items = fetch_mfds_safety_letters(limit=max_per_source)
            for item in items:
                item["_source"] = "mfds"
                item["_source_id"] = _SOURCE_ID_MFDS
            all_items.extend(items)
        except Exception as e:
            msg = f"MFDS 수집 오류: {e}"
            logger.error("[Collect] %s", msg)
            stats["errors"].append(msg)

    if "nemc" in sources:
        logger.info("[Collect] NEMC 수집 시작")
        try:
            items = fetch_nemc_first_aid()
            for item in items:
                item["_source"] = "nemc"
                item["_source_id"] = _SOURCE_ID_NEMC
            all_items.extend(items[:max_per_source])
        except Exception as e:
            msg = f"NEMC 수집 오류: {e}"
            logger.error("[Collect] %s", msg)
            stats["errors"].append(msg)

    if "kdca" in sources:
        logger.info("[Collect] KDCA 수집 시작 (max=%d)", max_per_source)
        try:
            items = fetch_kdca_openapi(api_key=kdca_key, limit=max_per_source)
            for item in items:
                item["_source"] = "kdca"
                item["_source_id"] = _SOURCE_ID_KDCA
            all_items.extend(items)
        except Exception as e:
            msg = f"KDCA 수집 오류: {e}"
            logger.error("[Collect] %s", msg)
            stats["errors"].append(msg)

    if "health_kdca" in sources:
        logger.info("[Collect] 국가건강정보포털 수집 시작 (max=%d)", max_per_source)
        try:
            items = fetch_health_kdca(limit=max_per_source)
            for item in items:
                item["_source"] = "health_kdca"
                item["_source_id"] = _SOURCE_ID_HEALTH_KDCA
            all_items.extend(items)
        except Exception as e:
            msg = f"health_kdca 수집 오류: {e}"
            logger.error("[Collect] %s", msg)
            stats["errors"].append(msg)

    stats["fetched"] = len(all_items)
    logger.info("[Collect] 총 %d건 수집 완료", stats["fetched"])

    # ── dry_run 미리보기 ─────────────────────────────────────
    if dry_run:
        print(f"\n[DRY RUN] 수집 총 {stats['fetched']}건 — 상위 {_DRY_RUN_PREVIEW}건 미리보기\n")
        for i, item in enumerate(all_items[:_DRY_RUN_PREVIEW]):
            print(f"{'─'*60}")
            print(f"[{i+1}] 출처: {item.get('_source', '?').upper()}")
            print(f"     제목: {item.get('title', '')}")
            print(f"     URL: {item.get('source_url', '')}")
            print(f"     체크섬: {item.get('source_checksum', '')[:16]}...")
            preview = item.get("content_md", "")[:200].replace("\n", " ")
            print(f"     내용: {preview}...")
        return stats

    # ── ingest 단계 ──────────────────────────────────────────
    from kb_ingest import ingest_document

    for item in all_items:
        title = item.get("title", "")
        content_md = item.get("content_md", "")
        source_id = item.get("_source_id", "")

        # 위반패턴 사전검사 (source_id 전달 → 공공 출처는 KB 콘텐츠 컨텍스트 적용)
        violations = precheck_violations(content_md, source_id=source_id)
        if violations:
            logger.info("[Collect] 위반 패턴 감지 — SKIP: %s | %s", title, violations[0])
            stats["skipped_violation"] += 1
            continue

        # evidence_topic 라벨링
        evidence_topic = label_evidence_topic(content_md, title=title)

        try:
            result = ingest_document(
                title=title,
                content_md=content_md,
                source_id=source_id,
                metadata={
                    "evidence_level": "B",
                    "symptom_tags": [],
                    "department": "general",
                },
                evidence_country="KR",
                evidence_topic=evidence_topic,
                regulatory_korea=True,
                upsert=False,
                status="active",
                source_url=item.get("source_url"),
                source_fetched_at=item.get("source_fetched_at"),
                source_checksum=item.get("source_checksum"),
            )

            if result["status"] == "skipped":
                stats["skipped_dup"] += 1
                logger.debug("[Collect] 중복 스킵: %s", title)
            else:
                stats["inserted"] += 1
                logger.info(
                    "[Collect] INSERT OK: %s (chunks=%d topic=%s)",
                    title, result["chunks_count"], evidence_topic,
                )

        except Exception as e:
            msg = f"ingest 오류 [{title[:50]}]: {e}"
            logger.error("[Collect] %s", msg)
            stats["errors"].append(msg)

    logger.info(
        "[Collect] 완료 — fetched=%d inserted=%d skipped_dup=%d "
        "skipped_violation=%d errors=%d",
        stats["fetched"], stats["inserted"],
        stats["skipped_dup"], stats["skipped_violation"],
        len(stats["errors"]),
    )
    return stats


# ════════════════════════════════════════════════════════════
#  CLI 진입점
# ════════════════════════════════════════════════════════════

def analyze_blocked_documents(source_id: str = "health_kdca", limit: int = 200) -> Dict:
    """
    차단된 문서 샘플 분석 (--analyze 모드).
    실제 수집은 하지 않고 fetch → precheck_violations만 수행하여
    차단 패턴 통계를 출력한다.

    Args:
        source_id: 분석할 출처 ID ('health_kdca' | 'nemc' | 'mfds' | 'kdca')
        limit:     분석할 최대 문서 수

    Returns:
        {
          'total': int,
          'blocked': int,
          'passed': int,
          'block_rate_pct': float,
          'category_counts': {rule_id: count},
          'samples': [{'title', 'violations', 'snippet'}]  # 최대 10건
        }
    """
    # 출처별 fetch 함수 매핑
    fetch_map = {
        "health_kdca": lambda: fetch_health_kdca(limit=limit),
        "nemc":        lambda: fetch_nemc_first_aid(),
        "mfds":        lambda: fetch_mfds_safety_letters(limit=limit),
        "kdca":        lambda: fetch_kdca_openapi(
                            api_key=os.environ.get("KDCA_API_KEY", ""), limit=limit
                        ),
    }

    if source_id not in fetch_map:
        logger.error("[Analyze] 지원하지 않는 source_id: %s", source_id)
        return {}

    logger.info("[Analyze] %s 문서 fetch 중 (최대 %d건)...", source_id, limit)
    items = fetch_map[source_id]()
    logger.info("[Analyze] %d건 fetch 완료 — 위반패턴 검사 시작", len(items))

    total = len(items)
    blocked_samples: List[Dict] = []
    category_counts: Dict[str, int] = {}

    for item in items:
        content_md = item.get("content_md", "")
        title = item.get("title", "")

        violations = precheck_violations(content_md, source_id=source_id)
        if not violations:
            continue

        # 카테고리별 집계
        for v_str in violations:
            rule_id = v_str.split(":")[0].strip()
            category_counts[rule_id] = category_counts.get(rule_id, 0) + 1

        # 매칭 발췌: 첫 번째 violation의 keyword/pattern 위치
        snippet = ""
        if violations:
            rule_id = violations[0].split(":")[0].strip()
            try:
                from config import VIOLATION_RULES
                rule = VIOLATION_RULES.get(rule_id, {})
                # 패턴 매칭으로 발췌 시도
                for pat in rule.get("patterns", []):
                    m = re.search(pat, content_md, re.IGNORECASE | re.DOTALL)
                    if m:
                        s = max(0, m.start() - 40)
                        e = min(len(content_md), m.end() + 40)
                        snippet = f"...{content_md[s:e]}..."
                        break
                # 패턴 미매칭이면 키워드로 시도
                if not snippet:
                    for kw in rule.get("keywords", []):
                        idx = content_md.find(kw)
                        if idx >= 0:
                            s = max(0, idx - 40)
                            e = min(len(content_md), idx + len(kw) + 40)
                            snippet = f"...{content_md[s:e]}..."
                            break
            except Exception:
                pass

        blocked_samples.append({
            "title": title,
            "violations": violations,
            "snippet": snippet,
        })

    blocked = len(blocked_samples)
    passed = total - blocked
    block_rate = round(blocked / total * 100, 1) if total > 0 else 0.0

    # 결과 출력
    print(f"\n{'='*60}")
    print(f"[분석 결과] source_id={source_id}, 총 {total}건")
    print(f"  통과: {passed}건  차단: {blocked}건  차단률: {block_rate}%")
    print(f"\n카테고리별 차단 건수:")
    for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {cnt}건")

    print(f"\n차단 샘플 (최대 10건):")
    for i, sample in enumerate(blocked_samples[:10]):
        print(f"\n  [{i+1}] {sample['title']}")
        print(f"       위반: {sample['violations'][0]}")
        if sample["snippet"]:
            clean_snippet = sample["snippet"].replace("\n", " ")[:120]
            print(f"       발췌: {clean_snippet}")

    print(f"\n{'='*60}")

    return {
        "total": total,
        "blocked": blocked,
        "passed": passed,
        "block_rate_pct": block_rate,
        "category_counts": category_counts,
        "samples": blocked_samples[:10],
    }


def _cli_main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(
        description="공공 의료 출처 자동 수집기 — RAG KB Phase 2"
    )
    parser.add_argument(
        "--source",
        choices=["mfds", "nemc", "kdca", "health_kdca", "all"],
        default="all",
        help="수집할 출처 (기본: all)",
    )
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=100,
        metavar="N",
        help="출처당 최대 수집 건수 (기본: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB INSERT 없이 샘플 미리보기만 출력",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="차단 패턴 분석 모드 — 실제 수집 없이 precheck_violations 통계만 출력",
    )
    args = parser.parse_args()

    # --analyze 모드: 수집 없이 차단 패턴 통계만 출력
    if args.analyze:
        analyze_source = "health_kdca" if args.source == "all" else args.source
        analyze_blocked_documents(
            source_id=analyze_source,
            limit=args.max_per_source,
        )
        sys.exit(0)

    sources = (
        None if args.source == "all"
        else [args.source]
    )

    if not args.dry_run:
        # DB 초기화 (로컬 SQLite 환경 대비)
        try:
            from rag_db import ensure_rag_schema
            ensure_rag_schema()  # RAG 소유 스키마 보장 — 전체 KB 스키마는 migrations/migrate_runner.py --sync 선행
        except Exception as e:
            logger.warning("[Collect] DB 초기화 오류 (무시): %s", e)

    stats = collect_all(
        max_per_source=args.max_per_source,
        dry_run=args.dry_run,
        sources=sources,
    )

    print("\n" + "="*50)
    print(f"수집: {stats['fetched']}건")
    if not args.dry_run:
        print(f"INSERT: {stats['inserted']}건")
        print(f"중복 스킵: {stats['skipped_dup']}건")
        print(f"위반 스킵: {stats['skipped_violation']}건")
        print(f"오류: {len(stats['errors'])}건")
        if stats["errors"]:
            for err in stats["errors"][:10]:
                print(f"  - {err}", file=sys.stderr)
    sys.exit(1 if stats["errors"] else 0)


if __name__ == "__main__":
    _cli_main()

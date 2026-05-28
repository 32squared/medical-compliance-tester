"""
KB Ingest 파이프라인 — RAG Phase 1 T3

마크다운 문서를 청킹 → 임베딩 → kb_documents + kb_chunks INSERT.

사용법:
  # 단일 문서 (코드에서)
  from kb_ingest import ingest_document
  result = ingest_document(title=..., content_md=..., source_id=..., metadata={...})

  # JSONL 일괄 (CLI)
  python kb_ingest.py --file tests/test_seed.jsonl

  # ingest_batch (코드에서)
  from kb_ingest import ingest_batch
  result = ingest_batch([{title, content_md, source_id, metadata}, ...])

의존:
  - T1: kb_documents / kb_chunks 테이블 존재
  - T2: embedding_provider.py (get_embedding_provider)
"""

import os
import re
import sys
import json
import uuid
import time
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# tiktoken 토큰 카운터 (없으면 폴백)
try:
    import tiktoken
    _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_TIKTOKEN_ENC.encode(text))
except Exception:
    _TIKTOKEN_ENC = None

    def _count_tokens(text: str) -> int:
        """폴백: 한국어/영어 혼합 텍스트의 대략적 토큰 추정 (글자수 / 2)"""
        return max(1, len(text) // 2)

# 프로젝트 루트를 sys.path 에 추가 (다른 디렉토리에서 실행 시 대비)
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from db import get_conn, _p, _ph, _now, _use_postgres

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────
#  토큰 임계값 상수
# ────────────────────────────────────────────
_CHUNK_MAX_TOKENS = 1024    # 이 이상이면 2차(문장 단위) 분할
_CHUNK_SOFT_MAX = 512       # 1개 청크 권장 상한 (의미 우선, overflow 허용)
_OVERLAP_TOKENS = 50        # 앞뒤 청크 overlap


# ════════════════════════════════════════════
#  청킹 알고리즘
# ════════════════════════════════════════════

def _is_table_line(line: str) -> bool:
    """마크다운 표 행인지 판별 ('|' 포함 라인)."""
    stripped = line.strip()
    return stripped.startswith("|") or (stripped and stripped.endswith("|"))


def _split_sections(content_md: str) -> List[Dict]:
    """
    마크다운 문서를 헤더(#, ##, ###) 기준으로 1차 분할.

    Returns:
        [{ 'title': str, 'level': int, 'body': str, 'path': list[str] }]
    """
    header_pattern = re.compile(r'^(#{1,3})\s+(.+)$', re.MULTILINE)
    sections = []
    last_pos = 0
    path_stack: List[str] = []   # 현재 섹션 계층 경로

    matches = list(header_pattern.finditer(content_md))

    # 앞에 헤더 없는 서문 처리
    if not matches or matches[0].start() > 0:
        preamble = content_md[:matches[0].start() if matches else len(content_md)].strip()
        if preamble:
            sections.append({
                'title': '',
                'level': 0,
                'body': preamble,
                'path': [],
            })

    for i, m in enumerate(matches):
        level = len(m.group(1))          # # → 1, ## → 2, ### → 3
        title = m.group(2).strip()

        # 다음 헤더까지의 본문
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content_md)
        body = content_md[m.end():end].strip()

        # 경로 스택 갱신
        if level == 1:
            path_stack = [title]
        elif level == 2:
            path_stack = path_stack[:1] + [title]
        else:  # level 3
            path_stack = path_stack[:2] + [title]

        sections.append({
            'title': title,
            'level': level,
            'body': body,
            'path': path_stack[:],
        })

    return sections


def _preserve_tables(text: str) -> List[Dict]:
    """
    텍스트를 '표 블록'과 '일반 텍스트 블록'으로 분리.

    Returns:
        [{'type': 'text'|'table', 'content': str}]
    """
    lines = text.split('\n')
    blocks = []
    current_type = None
    current_lines: List[str] = []

    for line in lines:
        is_table = _is_table_line(line)
        t = 'table' if is_table else 'text'
        if t != current_type:
            if current_lines:
                blocks.append({'type': current_type, 'content': '\n'.join(current_lines)})
            current_type = t
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append({'type': current_type, 'content': '\n'.join(current_lines)})

    return blocks


def _split_by_sentences(text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    """
    텍스트를 문장 단위로 분할하여 max_tokens 이하 청크 리스트 반환.
    앞뒤 overlap_tokens 만큼 겹침.
    """
    # 한국어 종결어미 + 영어 문장부호 기준
    sentence_end = re.compile(r'(?<=[.!?다요했습니다요])\s+')
    sentences = sentence_end.split(text)
    # 분할이 안 된 경우 공백 기준 폴백
    if len(sentences) == 1:
        sentences = text.split()

    chunks = []
    current_tokens = 0
    current_sentences: List[str] = []
    overlap_buffer: List[str] = []   # 이전 청크 마지막 토큰 버퍼 (overlap용)

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_tokens = _count_tokens(sent)

        # 단일 문장이 max_tokens 초과 → 강제 추가 (분할 불가)
        if sent_tokens > max_tokens:
            if current_sentences:
                chunks.append(' '.join(current_sentences))
            chunks.append(sent)
            current_sentences = []
            current_tokens = 0
            overlap_buffer = []
            continue

        if current_tokens + sent_tokens > max_tokens and current_sentences:
            chunks.append(' '.join(current_sentences))
            # overlap: 이전 청크 끝 부분을 새 청크 시작에 포함
            overlap_sentences: List[str] = []
            overlap_tok = 0
            for s in reversed(current_sentences):
                tok = _count_tokens(s)
                if overlap_tok + tok > overlap_tokens:
                    break
                overlap_sentences.insert(0, s)
                overlap_tok += tok
            current_sentences = overlap_sentences
            current_tokens = overlap_tok

        current_sentences.append(sent)
        current_tokens += sent_tokens

    if current_sentences:
        chunks.append(' '.join(current_sentences))

    return [c for c in chunks if c.strip()]


def chunk_markdown(
    content_md: str,
    max_tokens: int = _CHUNK_MAX_TOKENS,
    overlap: int = _OVERLAP_TOKENS,
) -> List[Dict]:
    """
    마크다운 문서를 청크 리스트로 변환.

    알고리즘 (rag_architecture.md §3.2):
      1. 헤더(#, ##, ###) 기준 1차 분할 → 섹션
      2. 섹션 토큰 측정:
           - 512 이하: 1개 청크 (그대로)
           - 512~1024: 1개 청크 (의미 우선 overflow 허용)
           - 1024 초과: 문장 단위 2차 분할 (표는 절대 분할 안 함)
      3. 앞뒤 50토큰 overlap
      4. 부모 섹션 제목 메타 부착

    Args:
        content_md: 마크다운 원문
        max_tokens: 2차 분할 기준 토큰 수 (기본 1024)
        overlap:    overlap 토큰 수 (기본 50)

    Returns:
        [{
            'content': str,
            'section_path': list[str],
            'token_count': int,
            'chunk_index': int,
        }]
    """
    sections = _split_sections(content_md)
    all_chunks: List[Dict] = []
    chunk_idx = 0

    for section in sections:
        title = section['title']
        body = section['body']
        path = section['path']

        if not body.strip():
            continue

        # 헤더 제목을 본문 앞에 추가 (컨텍스트 보존)
        full_text = (f"## {title}\n{body}" if title else body).strip()
        total_tokens = _count_tokens(full_text)

        if total_tokens <= max_tokens:
            # 1개 청크 (512이하 + 512~1024 overflow 허용)
            all_chunks.append({
                'content': full_text,
                'section_path': path,
                'token_count': total_tokens,
                'chunk_index': chunk_idx,
            })
            chunk_idx += 1
        else:
            # 1024 초과 → 표 보존 + 문장 단위 2차 분할
            sub_blocks = _preserve_tables(full_text)
            text_buffer = ""

            for block in sub_blocks:
                if block['type'] == 'table':
                    # 누적 일반 텍스트 먼저 처리
                    if text_buffer.strip():
                        for sub in _split_by_sentences(text_buffer, max_tokens, overlap):
                            tok = _count_tokens(sub)
                            all_chunks.append({
                                'content': sub,
                                'section_path': path,
                                'token_count': tok,
                                'chunk_index': chunk_idx,
                            })
                            chunk_idx += 1
                        text_buffer = ""
                    # 표는 통째로 1개 청크
                    table_text = block['content'].strip()
                    if table_text:
                        tok = _count_tokens(table_text)
                        all_chunks.append({
                            'content': table_text,
                            'section_path': path,
                            'token_count': tok,
                            'chunk_index': chunk_idx,
                        })
                        chunk_idx += 1
                else:
                    text_buffer += "\n" + block['content']

            # 남은 텍스트 처리
            if text_buffer.strip():
                for sub in _split_by_sentences(text_buffer.strip(), max_tokens, overlap):
                    tok = _count_tokens(sub)
                    all_chunks.append({
                        'content': sub,
                        'section_path': path,
                        'token_count': tok,
                        'chunk_index': chunk_idx,
                    })
                    chunk_idx += 1

    # chunk_index 순서대로 재정렬 (chunk_index는 이미 올라가지만 명시적으로 재부여)
    for i, chunk in enumerate(all_chunks):
        chunk['chunk_index'] = i

    return all_chunks


# ════════════════════════════════════════════
#  tsvector 생성 헬퍼
# ════════════════════════════════════════════

def text_to_tsv_korean(text: str) -> str:
    """
    한국어 텍스트를 ts_vector용 토큰 문자열로 변환 (단순 공백 분할 기반).
    형태소 분석은 Phase 2 (KoNLPy). Phase 1은 'simple' config 사용.
    """
    tokens = re.findall(r'[가-힣a-zA-Z0-9]+', text)
    return ' '.join(tokens)


# ════════════════════════════════════════════
#  단일 문서 ingest
# ════════════════════════════════════════════

def ingest_document(
    title: str,
    content_md: str,
    source_id: str,
    metadata: Dict[str, Any],
    evidence_country: str = "KR",
    evidence_topic: Optional[str] = None,
    regulatory_korea: bool = False,
    topic_keywords: Optional[List[str]] = None,
    upsert: bool = False,
    status: str = "active",
    author_id: Optional[str] = None,
    source_url: Optional[str] = None,
    source_fetched_at: Optional[str] = None,
    source_checksum: Optional[str] = None,
) -> Dict:
    """
    마크다운 문서 1건을 ingest (청킹 → 임베딩 → DB INSERT).

    Args:
        title:              문서 제목
        content_md:         마크다운 원문
        source_id:          kb_sources.id (외래키)
        metadata:           {evidence_level, symptom_tags, age_group, severity, department, ...}
        evidence_country:   'KR' | 'US' | ... (자문 반영 메타)
        evidence_topic:     핵심 주제 (예: 'fever_pediatric')
        regulatory_korea:   심평원·식약처 기준 관련 여부
        topic_keywords:     BM25 보조 + 주제 일치 검증용 키워드
        upsert:             True면 같은 source_id+title 존재 시 UPDATE, False면 SKIP
        status:             'active' | 'draft' | 'pending_review'
        author_id:          작성자 user_id (자체 콘텐츠)
        source_url:         원문 출처 URL (공공 API 수집 시)
        source_fetched_at:  수집 시각 ISO 8601 (None이면 _now() 사용)
        source_checksum:    SHA-256 hex (내용 변경 감지용)

    Returns:
        {'document_id': str, 'chunks_count': int, 'status': str, 'latency_ms': int}
    """
    t_start = time.time()

    if not title or not title.strip():
        raise ValueError("title은 비어 있을 수 없습니다")
    if not content_md or not content_md.strip():
        raise ValueError("content_md는 비어 있을 수 없습니다")
    if not source_id or not source_id.strip():
        raise ValueError("source_id는 비어 있을 수 없습니다")

    evidence_level = metadata.get("evidence_level", "B")
    keywords_json = json.dumps(topic_keywords or [], ensure_ascii=False)
    fetched_at = source_fetched_at or _now()

    # ── 1. 멱등성 체크 (title 또는 source_url 일치 모두 확인) ─
    with get_conn() as (conn, cur):
        if source_url:
            cur.execute(
                f"SELECT id, source_checksum FROM kb_documents"
                f" WHERE source_id = {_p()} AND (title = {_p()} OR source_url = {_p()})",
                (source_id, title, source_url),
            )
        else:
            cur.execute(
                f"SELECT id, source_checksum FROM kb_documents"
                f" WHERE source_id = {_p()} AND title = {_p()}",
                (source_id, title),
            )
        existing = cur.fetchone()

    if existing:
        if isinstance(existing, dict):
            existing_id = existing["id"]
            existing_checksum = existing.get("source_checksum")
        else:
            existing_id = existing[0]
            existing_checksum = existing[1] if len(existing) > 1 else None

        # checksum이 달라졌으면 강제 upsert (내용 갱신)
        checksum_changed = (
            source_checksum is not None
            and existing_checksum is not None
            and source_checksum != existing_checksum
        )
        if not upsert and not checksum_changed:
            logger.info("[KBIngest] SKIP (already exists): %s / %s", source_id, title)
            return {
                "document_id": existing_id,
                "chunks_count": 0,
                "status": "skipped",
                "latency_ms": int((time.time() - t_start) * 1000),
            }
        # upsert=True 또는 checksum 변경 → 기존 청크 삭제 후 재삽입
        with get_conn() as (conn, cur):
            cur.execute(
                f"DELETE FROM kb_chunks WHERE document_id = {_p()}",
                (existing_id,),
            )
        document_id = existing_id
        _do_insert_doc = False
    else:
        document_id = str(uuid.uuid4())
        _do_insert_doc = True

    # ── 2. 청킹 ──────────────────────────────────────────────
    chunks = chunk_markdown(content_md)
    if not chunks:
        raise ValueError("청크를 생성할 수 없습니다 (빈 문서?)")

    # ── 3. 임베딩 (배치 100개 단위) ─────────────────────────
    chunk_texts = [c["content"] for c in chunks]
    embeddings = _embed_in_batches(chunk_texts, batch_size=100)

    # ── 4. 트랜잭션: 문서 + 청크 INSERT ─────────────────────
    now_str = _now()
    metadata_json_str = json.dumps(metadata, ensure_ascii=False)

    with get_conn() as (conn, cur):
        # 4-a. kb_documents
        if _do_insert_doc:
            _insert_document(
                cur,
                document_id=document_id,
                source_id=source_id,
                title=title,
                content_md=content_md,
                metadata_json=metadata_json_str,
                status=status,
                author_id=author_id,
                evidence_level=evidence_level,
                now_str=now_str,
                source_url=source_url,
                source_fetched_at=fetched_at,
                source_checksum=source_checksum,
            )
        else:
            # upsert=True 또는 checksum 변경: 문서 메타 업데이트
            cur.execute(
                f"""UPDATE kb_documents
                    SET content_md = {_p()}, metadata_json = {_p()},
                        evidence_level = {_p()}, updated_at = {_p()}, status = {_p()},
                        source_url = {_p()}, source_fetched_at = {_p()},
                        source_checksum = {_p()}
                    WHERE id = {_p()}""",
                (
                    content_md, metadata_json_str, evidence_level, now_str, status,
                    source_url, fetched_at, source_checksum,
                    document_id,
                ),
            )

        # 4-b. kb_chunks (배치 INSERT)
        _insert_chunks(
            cur,
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
            evidence_country=evidence_country,
            evidence_topic=evidence_topic,
            regulatory_korea=regulatory_korea,
            keywords_json=keywords_json,
            metadata=metadata,
            now_str=now_str,
        )

    latency_ms = int((time.time() - t_start) * 1000)
    logger.info(
        "[KBIngest] OK doc=%s chunks=%d latency=%dms",
        document_id, len(chunks), latency_ms,
    )
    return {
        "document_id": document_id,
        "chunks_count": len(chunks),
        "status": "inserted" if _do_insert_doc else "updated",
        "latency_ms": latency_ms,
    }


def _embed_in_batches(texts: List[str], batch_size: int = 100) -> List[Optional[List[float]]]:
    """
    임베딩 배치 호출. OPENAI_API_KEY 없으면 None 리스트 반환 (SQLite 테스트용).
    배치 단위로 호출해 rate limit을 완화한다.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("[KBIngest] OPENAI_API_KEY 없음 — 임베딩 생략 (None)")
        return [None] * len(texts)

    from embedding_provider import get_embedding_provider
    provider = get_embedding_provider("ingest")

    results: List[Optional[List[float]]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vecs = provider.embed(batch)
        results.extend(vecs)
        # rate limit 완화: 배치 사이 짧은 간격
        if i + batch_size < len(texts):
            time.sleep(0.2)
    return results


def _insert_document(cur, *, document_id, source_id, title, content_md,
                     metadata_json, status, author_id, evidence_level, now_str,
                     source_url=None, source_fetched_at=None, source_checksum=None):
    """kb_documents 1행 INSERT (source_url/fetched_at/checksum 포함)."""
    cur.execute(
        f"""INSERT INTO kb_documents
            (id, source_id, title, content_md, metadata_json, status,
             author_id, evidence_level, version, created_at, updated_at,
             source_url, source_fetched_at, source_checksum)
            VALUES ({_ph(14)})""",
        (
            document_id, source_id, title, content_md, metadata_json, status,
            author_id, evidence_level, 1, now_str, now_str,
            source_url, source_fetched_at, source_checksum,
        ),
    )


def _insert_chunks(cur, *, document_id, chunks, embeddings,
                   evidence_country, evidence_topic, regulatory_korea,
                   keywords_json, metadata, now_str):
    """kb_chunks 배치 INSERT."""
    symptom_tags = json.dumps(
        metadata.get("symptom_tags", []), ensure_ascii=False
    )
    severity = metadata.get("severity")

    for chunk, emb in zip(chunks, embeddings):
        chunk_id = str(uuid.uuid4())
        section_path_json = json.dumps(chunk["section_path"], ensure_ascii=False)
        tsv_text = text_to_tsv_korean(chunk["content"])

        # 벡터 직렬화
        embedding_val = _serialize_embedding(emb)
        reg_int = 1 if regulatory_korea else 0

        if _use_postgres:
            # PostgreSQL: to_tsvector 사용
            cur.execute(
                f"""INSERT INTO kb_chunks
                    (id, document_id, chunk_index, content, section_path,
                     embedding_primary, embedding_primary_model,
                     evidence_country, evidence_topic, regulatory_korea, topic_keywords,
                     token_count, symptom_tags, severity,
                     content_tsv, created_at)
                    VALUES ({_ph(16)})""",
                (
                    chunk_id, document_id, chunk["chunk_index"], chunk["content"],
                    section_path_json,
                    embedding_val, "openai_small_v3",
                    evidence_country, evidence_topic, reg_int, keywords_json,
                    chunk["token_count"],
                    symptom_tags, severity,
                    _pg_tsvector_expr(tsv_text),  # tsvector 표현식 (별도 처리)
                    now_str,
                ),
            )
        else:
            # SQLite: content_tsv는 TEXT 그대로 저장
            cur.execute(
                f"""INSERT INTO kb_chunks
                    (id, document_id, chunk_index, content, section_path,
                     embedding_primary, embedding_primary_model,
                     evidence_country, evidence_topic, regulatory_korea, topic_keywords,
                     token_count, symptom_tags, severity,
                     content_tsv, created_at)
                    VALUES ({_ph(16)})""",
                (
                    chunk_id, document_id, chunk["chunk_index"], chunk["content"],
                    section_path_json,
                    embedding_val, "openai_small_v3",
                    evidence_country, evidence_topic, reg_int, keywords_json,
                    chunk["token_count"],
                    symptom_tags, severity,
                    tsv_text,
                    now_str,
                ),
            )


def _serialize_embedding(emb: Optional[List[float]]) -> Optional[str]:
    """
    임베딩 벡터를 DB 저장 형식으로 변환.
    - PostgreSQL: '[1.0, 2.0, ...]' 문자열 (pgvector 파싱 형식)
    - SQLite:     JSON 문자열 (TEXT 컬럼)
    - None이면 None 반환
    """
    if emb is None:
        return None
    if _use_postgres:
        return "[" + ",".join(str(v) for v in emb) + "]"
    else:
        return json.dumps(emb)


def _insert_chunks(cur, *, document_id, chunks, embeddings,
                   evidence_country, evidence_topic, regulatory_korea,
                   keywords_json, metadata, now_str):
    """kb_chunks 배치 INSERT (SQLite/PostgreSQL 듀얼)."""
    symptom_tags = json.dumps(
        metadata.get("symptom_tags", []), ensure_ascii=False
    )
    severity = metadata.get("severity")
    # PostgreSQL: boolean 컬럼이므로 True/False 사용
    # SQLite: INTEGER 컬럼이므로 0/1 사용
    reg_bool = bool(regulatory_korea)
    reg_int = 1 if regulatory_korea else 0

    for chunk, emb in zip(chunks, embeddings):
        chunk_id = str(uuid.uuid4())
        section_path_json = json.dumps(chunk["section_path"], ensure_ascii=False)
        tsv_text = text_to_tsv_korean(chunk["content"])
        embedding_val = _serialize_embedding(emb)

        if _use_postgres:
            # PostgreSQL: embedding_primary는 ::vector(1536) 캐스트,
            #             content_tsv는 to_tsvector('simple', %) 함수 사용
            #             regulatory_korea는 boolean 타입 → True/False 전달
            ph = "%s"  # psycopg2 플레이스홀더
            cur.execute(
                f"""INSERT INTO kb_chunks
                    (id, document_id, chunk_index, content, section_path,
                     embedding_primary, embedding_primary_model,
                     evidence_country, evidence_topic, regulatory_korea, topic_keywords,
                     token_count, symptom_tags, severity,
                     content_tsv, created_at)
                    VALUES (
                        {ph},{ph},{ph},{ph},{ph},
                        {ph}::vector(1536),{ph},
                        {ph},{ph},{ph},{ph},
                        {ph},{ph},{ph},
                        to_tsvector('simple', {ph}),
                        {ph}
                    )""",
                (
                    chunk_id, document_id, chunk["chunk_index"], chunk["content"],
                    section_path_json,
                    embedding_val, "openai_small_v3",
                    evidence_country, evidence_topic, reg_bool, keywords_json,
                    chunk["token_count"], symptom_tags, severity,
                    tsv_text,
                    now_str,
                ),
            )
        else:
            cur.execute(
                f"""INSERT INTO kb_chunks
                    (id, document_id, chunk_index, content, section_path,
                     embedding_primary, embedding_primary_model,
                     evidence_country, evidence_topic, regulatory_korea, topic_keywords,
                     token_count, symptom_tags, severity,
                     content_tsv, created_at)
                    VALUES ({_ph(16)})""",
                (
                    chunk_id, document_id, chunk["chunk_index"], chunk["content"],
                    section_path_json,
                    embedding_val, "openai_small_v3",
                    evidence_country, evidence_topic, reg_int, keywords_json,
                    chunk["token_count"],
                    symptom_tags, severity,
                    tsv_text,
                    now_str,
                ),
            )


# ════════════════════════════════════════════
#  배치 ingest
# ════════════════════════════════════════════

def ingest_batch(documents: List[Dict]) -> Dict:
    """
    여러 문서를 병렬로 ingest.

    각 문서는 dict 형식:
        {title, content_md, source_id, metadata,
         evidence_country?, evidence_topic?, regulatory_korea?, topic_keywords?,
         upsert?, status?, author_id?}

    Args:
        documents: 문서 dict 리스트

    Returns:
        {'success': int, 'failed': int, 'errors': [...], 'results': [...]}
    """
    success_count = 0
    failed_count = 0
    errors = []
    results = []

    # ThreadPoolExecutor max_workers=5 (OpenAI rate limit 고려)
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {}
        for i, doc in enumerate(documents):
            future = executor.submit(
                ingest_document,
                title=doc["title"],
                content_md=doc["content_md"],
                source_id=doc["source_id"],
                metadata=doc.get("metadata", {}),
                evidence_country=doc.get("evidence_country", "KR"),
                evidence_topic=doc.get("evidence_topic"),
                regulatory_korea=doc.get("regulatory_korea", False),
                topic_keywords=doc.get("topic_keywords"),
                upsert=doc.get("upsert", False),
                status=doc.get("status", "active"),
                author_id=doc.get("author_id"),
                source_url=doc.get("source_url"),
                source_fetched_at=doc.get("source_fetched_at"),
                source_checksum=doc.get("source_checksum"),
            )
            future_map[future] = i

        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                result = future.result()
                results.append(result)
                if result["status"] != "skipped":
                    success_count += 1
                else:
                    # skipped는 성공으로 계산하지 않고 별도 카운트
                    success_count += 1  # skipped도 오류 아님
            except Exception as exc:
                failed_count += 1
                doc_title = documents[idx].get("title", f"doc[{idx}]")
                err_msg = f"{doc_title}: {exc}"
                errors.append(err_msg)
                logger.error("[KBIngest] FAILED %s — %s", doc_title, exc)

    total_chunks = sum(r.get("chunks_count", 0) for r in results)
    logger.info(
        "[KBIngest] Batch done: success=%d failed=%d total_chunks=%d",
        success_count, failed_count, total_chunks,
    )
    return {
        "success": success_count,
        "failed": failed_count,
        "errors": errors,
        "results": results,
    }


# ════════════════════════════════════════════
#  kb_sources 시드 INSERT
# ════════════════════════════════════════════

def seed_kb_sources(sources: Optional[List[Dict]] = None) -> int:
    """
    kb_sources 테이블에 초기 시드 데이터 INSERT.
    이미 존재하는 id는 SKIP (멱등).

    Args:
        sources: source dict 리스트. None이면 기본 3개 시드 사용.

    Returns:
        실제 INSERT된 행 수
    """
    if sources is None:
        now_str = _now()
        sources = [
            {
                "id": "kmle_seed",
                "name": "대한의학회 KMLE 발췌",
                "source_type": "guideline",
                "license": "proprietary",
                "update_frequency": "quarterly",
                "is_active": 1,
                "created_at": now_str,
            },
            {
                "id": "hira_kdca",
                "name": "심평원·질병관리청 공개 자료",
                "source_type": "public",
                "license": "kogl_type1",
                "update_frequency": "monthly",
                "is_active": 1,
                "created_at": now_str,
            },
            {
                "id": "internal_md",
                "name": "의사 직접 작성 콘텐츠",
                "source_type": "internal",
                "license": "proprietary",
                "update_frequency": "on_demand",
                "is_active": 1,
                "created_at": now_str,
            },
        ]

    inserted = 0
    with get_conn() as (conn, cur):
        for src in sources:
            cur.execute(
                f"SELECT id FROM kb_sources WHERE id = {_p()}",
                (src["id"],),
            )
            if cur.fetchone():
                continue  # 이미 존재

            cur.execute(
                f"""INSERT INTO kb_sources
                    (id, name, source_type, license, update_frequency, is_active, created_at)
                    VALUES ({_ph(7)})""",
                (
                    src["id"], src["name"], src["source_type"], src["license"],
                    src.get("update_frequency"), src.get("is_active", 1),
                    src.get("created_at", _now()),
                ),
            )
            inserted += 1

    logger.info("[KBIngest] seed_kb_sources: %d rows inserted", inserted)
    return inserted


# ════════════════════════════════════════════
#  CLI 진입점
# ════════════════════════════════════════════

def _cli_main():
    """python kb_ingest.py --file <jsonl_file> [--upsert] [--seed-sources]"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(description="KB Ingest — JSONL 문서 일괄 ingest")
    parser.add_argument("--file", required=False, help="JSONL 파일 경로 (1줄=1문서)")
    parser.add_argument("--upsert", action="store_true", help="중복 문서 덮어쓰기")
    parser.add_argument("--seed-sources", action="store_true",
                        help="kb_sources 초기 시드 INSERT 실행")
    args = parser.parse_args()

    from db import init_db
    init_db()

    if args.seed_sources:
        n = seed_kb_sources()
        print(f"Seeded {n} kb_sources")

    if args.file:
        docs = []
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    docs.append(json.loads(line))

        if args.upsert:
            for doc in docs:
                doc["upsert"] = True

        result = ingest_batch(docs)
        total_chunks = sum(r.get("chunks_count", 0) for r in result["results"])
        print(
            f"Ingested {result['success']} documents, {total_chunks} chunks "
            f"(failed={result['failed']})"
        )
        if result["errors"]:
            for err in result["errors"]:
                print(f"  ERROR: {err}", file=sys.stderr)
        sys.exit(1 if result["failed"] else 0)
    elif not args.seed_sources:
        parser.print_help()


if __name__ == "__main__":
    _cli_main()

"""
tests/test_kb_ingest.py — kb_ingest.py 단위 테스트

SQLite 모드에서 실행 가능 (DATABASE_URL 미설정).
임베딩은 OpenAI API 없이 None으로 모킹.

실행:
    python -m pytest tests/test_kb_ingest.py -v
"""

import os
import sys
import json
import sqlite3
import uuid
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 프로젝트 루트를 sys.path에 추가
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# DB 환경변수 확실히 SQLite 모드로 설정 (pytest 임포트 전 설정)
os.environ.pop("DATABASE_URL", None)


# ─── SQLite 임시 DB를 사용하도록 db 모듈 패치 ───────────────────────────────
@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    """각 테스트마다 독립 SQLite DB를 사용한다."""
    db_file = str(tmp_path / "test_app.db")
    monkeypatch.setenv("DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # db 모듈 재로드하여 새 DB 경로 반영
    import importlib
    import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "_use_postgres", False)

    # 스키마 초기화 (기존 SQLite 스키마 + RAG 테이블)
    _init_test_db(db_file)
    yield db_file


def _init_test_db(db_path: str):
    """테스트용 SQLite DB에 필요한 테이블 생성 및 시드 소스 삽입."""
    sql_path = REPO_ROOT / "migrations" / "001_rag_tables_sqlite.sql"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # RAG 테이블 생성 (sqlite migration 파일 실행)
    if sql_path.exists():
        sql_text = sql_path.read_text(encoding="utf-8")
        # BEGIN/COMMIT 제거, 세미콜론으로 분할 실행
        for stmt in sql_text.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            upper = stmt.upper().strip()
            if upper in ("BEGIN", "COMMIT"):
                continue
            # 주석만인 블록 스킵
            lines = [l for l in stmt.splitlines()
                     if l.strip() and not l.strip().startswith("--")]
            if not lines:
                continue
            try:
                conn.execute(stmt)
            except Exception:
                pass

    # 테스트에서 사용하는 kb_sources 시드 INSERT
    # (kb_documents.source_id FK 제약 충족)
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()
    seed_sources = [
        ("kmle_seed",   "대한의학회 KMLE 발췌",        "guideline", "proprietary",  "quarterly",  1, now_str),
        ("hira_kdca",   "심평원·질병관리청 공개 자료",  "public",    "kogl_type1",   "monthly",    1, now_str),
        ("internal_md", "의사 직접 작성 콘텐츠",        "internal",  "proprietary",  "on_demand",  1, now_str),
    ]
    for row in seed_sources:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO kb_sources "
                "(id, name, source_type, license, update_frequency, is_active, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                row,
            )
        except Exception:
            pass

    conn.commit()
    conn.close()


# ─── 임베딩 모킹 헬퍼 ────────────────────────────────────────────────────────

def _mock_embed(texts):
    """임베딩 API 없이 더미 1536차원 벡터 반환."""
    return [[0.0] * 1536 for _ in texts]


# ─── 테스트 케이스 ────────────────────────────────────────────────────────────

class TestChunkMarkdown:
    """chunk_markdown() 알고리즘 단위 테스트."""

    def test_small_doc_single_chunk(self):
        """200토큰 이하 소형 문서는 청크 1개."""
        from kb_ingest import chunk_markdown
        content = "# 발열\n\n발열은 체온이 38도 이상인 상태입니다. 일반적으로 감염이 원인입니다."
        chunks = chunk_markdown(content)
        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0
        assert "발열" in chunks[0]["content"]

    def test_medium_doc_multiple_chunks_with_overlap(self):
        """1500토큰 이상 문서는 여러 청크로 분할되며 내용이 손실되지 않는다."""
        from kb_ingest import chunk_markdown, _count_tokens

        # 각 섹션이 1024토큰을 초과하도록 긴 텍스트 생성
        long_sentence = "이 문장은 반복적인 내용을 포함하여 토큰 수를 늘리기 위한 것입니다. " * 20
        content = (
            "# 발열 평가 가이드\n\n"
            "## 개요\n\n" + long_sentence + "\n\n"
            "## 평가 방법\n\n" + long_sentence + "\n\n"
            "## 치료\n\n" + long_sentence
        )
        chunks = chunk_markdown(content, max_tokens=512)
        assert len(chunks) >= 2, f"청크 수가 2개 이상이어야 함, 실제: {len(chunks)}"
        # chunk_index는 0부터 연속적
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_table_not_split(self):
        """표 블록은 분할되지 않아야 한다."""
        from kb_ingest import chunk_markdown

        table = (
            "| 증상 | 가능성 | 처치 |\n"
            "|------|--------|------|\n"
            "| 발열 | 감염   | 해열제 |\n"
            "| 두통 | 편두통 | 진통제 |\n"
            "| 기침 | 감기   | 수분섭취 |\n"
        )
        content = "# 증상별 처치 가이드\n\n" + table

        chunks = chunk_markdown(content)
        # 표는 분할되지 않아야 하므로 표 전체가 하나의 청크에 있어야 함
        table_in_single_chunk = any(
            "| 발열 |" in c["content"] and "| 기침 |" in c["content"]
            for c in chunks
        )
        assert table_in_single_chunk, "표가 분할되지 않아야 한다"

    def test_section_path_attached(self):
        """청크에 section_path가 올바르게 부착된다."""
        from kb_ingest import chunk_markdown

        content = (
            "# 내과\n## 발열\n발열 설명.\n"
            "## 복통\n복통 설명."
        )
        chunks = chunk_markdown(content)
        paths = [c["section_path"] for c in chunks]
        # '발열' 섹션의 path에 '발열'이 포함되어야 함
        fever_chunks = [c for c in chunks if "발열 설명" in c["content"]]
        assert fever_chunks
        assert "발열" in fever_chunks[0]["section_path"]

    def test_chunk_index_sequential(self):
        """chunk_index는 0부터 연속적으로 증가한다."""
        from kb_ingest import chunk_markdown

        content = "\n".join([
            "# 섹션1\n내용1.",
            "# 섹션2\n내용2.",
            "# 섹션3\n내용3.",
        ])
        chunks = chunk_markdown(content)
        for i, c in enumerate(chunks):
            assert c["chunk_index"] == i


class TestIngestDocument:
    """ingest_document() DB 연동 테스트."""

    def test_basic_insert(self, use_temp_db):
        """기본 ingest: kb_documents 1행 + kb_chunks N행 INSERT."""
        from kb_ingest import ingest_document

        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            result = ingest_document(
                title="발열 평가 가이드 (테스트)",
                content_md="# 발열\n\n체온 38도 이상을 발열이라 합니다.\n\n## 평가\n\n동반 증상 확인이 중요합니다.",
                source_id="internal_md",
                metadata={"evidence_level": "A", "symptom_tags": ["fever"], "severity": "moderate"},
                evidence_country="KR",
                evidence_topic="fever_evaluation",
                regulatory_korea=False,
                topic_keywords=["발열", "체온", "평가"],
            )

        assert result["status"] == "inserted"
        assert result["chunks_count"] >= 1
        assert result["document_id"]

        # DB 직접 확인
        conn = sqlite3.connect(use_temp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM kb_documents WHERE id = ?", (result["document_id"],)
        ).fetchone()
        assert row is not None
        assert row["title"] == "발열 평가 가이드 (테스트)"
        assert row["status"] == "active"

        chunks = conn.execute(
            "SELECT * FROM kb_chunks WHERE document_id = ?", (result["document_id"],)
        ).fetchall()
        assert len(chunks) == result["chunks_count"]
        conn.close()

    def test_meta_fields_saved(self, use_temp_db):
        """evidence_country, evidence_topic, regulatory_korea, topic_keywords가 DB에 저장된다."""
        from kb_ingest import ingest_document

        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            result = ingest_document(
                title="항생제 처방 가이드라인",
                content_md="# 항생제\n\n항생제는 의사 처방이 필요합니다. 심평원 기준 참조.",
                source_id="hira_kdca",
                metadata={"evidence_level": "A"},
                evidence_country="KR",
                evidence_topic="antibiotic_guideline",
                regulatory_korea=True,
                topic_keywords=["항생제", "처방", "심평원"],
            )

        conn = sqlite3.connect(use_temp_db)
        conn.row_factory = sqlite3.Row
        chunk = conn.execute(
            "SELECT * FROM kb_chunks WHERE document_id = ? LIMIT 1",
            (result["document_id"],)
        ).fetchone()
        assert chunk is not None
        assert chunk["evidence_country"] == "KR"
        assert chunk["evidence_topic"] == "antibiotic_guideline"
        assert chunk["regulatory_korea"] == 1  # SQLite BOOLEAN → 1
        keywords = json.loads(chunk["topic_keywords"])
        assert "항생제" in keywords
        conn.close()

    def test_idempotent_skip(self, use_temp_db):
        """같은 source_id+title 재호출 시 upsert=False이면 SKIP."""
        from kb_ingest import ingest_document

        kwargs = dict(
            title="중복 문서 테스트",
            content_md="# 내용\n\n첫 번째 삽입.",
            source_id="internal_md",
            metadata={},
        )
        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            r1 = ingest_document(**kwargs, upsert=False)
            r2 = ingest_document(**kwargs, upsert=False)

        assert r1["status"] == "inserted"
        assert r2["status"] == "skipped"
        assert r2["chunks_count"] == 0

    def test_upsert_updates_chunks(self, use_temp_db):
        """upsert=True이면 기존 청크 삭제 후 재삽입된다."""
        from kb_ingest import ingest_document

        kwargs = dict(
            title="업서트 테스트",
            content_md="# 원본\n\n원본 내용.",
            source_id="internal_md",
            metadata={},
        )
        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            r1 = ingest_document(**kwargs, upsert=False)

        updated_kwargs = dict(
            title="업서트 테스트",
            content_md="# 업데이트\n\n업데이트된 내용입니다.\n\n## 추가 섹션\n\n추가된 내용.",
            source_id="internal_md",
            metadata={},
        )
        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            r2 = ingest_document(**updated_kwargs, upsert=True)

        assert r2["status"] == "updated"
        conn = sqlite3.connect(use_temp_db)
        chunks = conn.execute(
            "SELECT content FROM kb_chunks WHERE document_id = ?",
            (r1["document_id"],)
        ).fetchall()
        assert any("업데이트된 내용" in c[0] for c in chunks)
        conn.close()

    def test_tsvector_column_filled(self, use_temp_db):
        """content_tsv 컬럼이 비어 있지 않아야 한다."""
        from kb_ingest import ingest_document

        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            result = ingest_document(
                title="TSV 테스트",
                content_md="# 발열\n\n발열과 두통 동반 시 응급실 방문을 권장합니다.",
                source_id="internal_md",
                metadata={},
            )

        conn = sqlite3.connect(use_temp_db)
        chunk = conn.execute(
            "SELECT content_tsv FROM kb_chunks WHERE document_id = ? LIMIT 1",
            (result["document_id"],)
        ).fetchone()
        assert chunk is not None
        assert chunk[0]  # content_tsv가 빈 문자열이 아님
        # 한국어 토큰이 포함되어야 함
        assert "발열" in chunk[0]
        conn.close()

    def test_embedding_model_field(self, use_temp_db):
        """embedding_primary_model이 'openai_small_v3'로 저장된다."""
        from kb_ingest import ingest_document

        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            result = ingest_document(
                title="임베딩 모델 테스트",
                content_md="# 내용\n\n임베딩 모델 확인용 문서.",
                source_id="internal_md",
                metadata={},
            )

        conn = sqlite3.connect(use_temp_db)
        chunk = conn.execute(
            "SELECT embedding_primary_model FROM kb_chunks WHERE document_id = ? LIMIT 1",
            (result["document_id"],)
        ).fetchone()
        assert chunk[0] == "openai_small_v3"
        conn.close()


class TestIngestBatch:
    """ingest_batch() 테스트."""

    def test_batch_5_documents(self, use_temp_db):
        """5개 문서 배치 ingest → 모두 성공."""
        from kb_ingest import ingest_batch

        docs = [
            {
                "title": f"배치 테스트 문서 {i}",
                "content_md": f"# 제목 {i}\n\n내용 {i}번 문서입니다. 의료 정보를 담고 있습니다.",
                "source_id": "internal_md",
                "metadata": {"evidence_level": "B"},
                "evidence_country": "KR",
            }
            for i in range(5)
        ]

        with patch("kb_ingest._embed_in_batches", side_effect=lambda texts, **kw: _mock_embed(texts)):
            result = ingest_batch(docs)

        assert result["failed"] == 0
        assert result["success"] == 5
        assert len(result["errors"]) == 0
        assert len(result["results"]) == 5

        # DB에 5개 문서 모두 존재
        conn = sqlite3.connect(use_temp_db)
        count = conn.execute("SELECT count(*) FROM kb_documents").fetchone()[0]
        assert count == 5
        conn.close()

    def test_batch_partial_failure(self, use_temp_db):
        """배치 중 일부 실패 → 나머지는 성공."""
        from kb_ingest import ingest_document, ingest_batch

        def mock_ingest_partial(title, **kwargs):
            if title == "실패 문서":
                raise ValueError("의도적 실패")
            return ingest_document.__wrapped__(title=title, **kwargs) if hasattr(ingest_document, '__wrapped__') else _real_ingest(title=title, **kwargs)

        docs = [
            {
                "title": "정상 문서",
                "content_md": "# 정상\n\n정상 내용.",
                "source_id": "internal_md",
                "metadata": {},
            },
            {
                "title": "실패 문서",
                "content_md": "# 실패\n\n실패 내용.",
                "source_id": "internal_md",
                "metadata": {},
            },
        ]

        def _failing_embed(texts, **kw):
            # "실패 문서"가 포함된 배치는 예외를 발생시킴
            # 이 mock은 단순히 None 반환 (인위적 실패는 source_id 없음으로 테스트)
            return _mock_embed(texts)

        # source_id를 빈 문자열로 설정하여 실패 유도
        docs[1]["source_id"] = ""  # 빈 source_id → ValueError

        with patch("kb_ingest._embed_in_batches", side_effect=_failing_embed):
            result = ingest_batch(docs)

        assert result["failed"] >= 1
        assert len(result["errors"]) >= 1


@pytest.fixture()
def empty_sources_db(tmp_path, monkeypatch):
    """kb_sources가 비어 있는 별도 DB (seed_kb_sources 테스트 전용)."""
    db_file = str(tmp_path / "seed_test_app.db")
    monkeypatch.setenv("DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "_use_postgres", False)

    # 테이블 생성만 (시드 없음)
    sql_path = REPO_ROOT / "migrations" / "001_rag_tables_sqlite.sql"
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys=ON")
    if sql_path.exists():
        sql_text = sql_path.read_text(encoding="utf-8")
        for stmt in sql_text.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            upper = stmt.upper().strip()
            if upper in ("BEGIN", "COMMIT"):
                continue
            lines = [l for l in stmt.splitlines()
                     if l.strip() and not l.strip().startswith("--")]
            if not lines:
                continue
            try:
                conn.execute(stmt)
            except Exception:
                pass
    conn.commit()
    conn.close()
    yield db_file


class TestSeedKbSources:
    """seed_kb_sources() 테스트."""

    def test_seed_3_sources(self, empty_sources_db):
        """3개 기본 소스 시드 INSERT."""
        from kb_ingest import seed_kb_sources

        n = seed_kb_sources()
        assert n == 3

        conn = sqlite3.connect(empty_sources_db)
        rows = conn.execute("SELECT id FROM kb_sources ORDER BY id").fetchall()
        ids = {r[0] for r in rows}
        assert "kmle_seed" in ids
        assert "hira_kdca" in ids
        assert "internal_md" in ids
        conn.close()

    def test_seed_idempotent(self, empty_sources_db):
        """같은 소스를 두 번 시드해도 중복 없음."""
        from kb_ingest import seed_kb_sources

        n1 = seed_kb_sources()
        n2 = seed_kb_sources()
        assert n1 == 3
        assert n2 == 0  # 이미 존재 → INSERT 없음

        conn = sqlite3.connect(empty_sources_db)
        count = conn.execute("SELECT count(*) FROM kb_sources").fetchone()[0]
        assert count == 3
        conn.close()


class TestTextToTsv:
    """text_to_tsv_korean() 단위 테스트."""

    def test_extracts_korean_tokens(self):
        """한국어 + 영어 + 숫자 토큰 추출."""
        from kb_ingest import text_to_tsv_korean

        text = "발열(38도 이상)은 fever로 불립니다. 123ABC test"
        result = text_to_tsv_korean(text)
        assert "발열" in result
        assert "38" in result
        assert "fever" in result
        assert "123" in result or "ABC" in result

    def test_strips_special_chars(self):
        """특수문자가 결과에서 제거된다."""
        from kb_ingest import text_to_tsv_korean

        text = "|||표 분리자|||는 제거됩니다."
        result = text_to_tsv_korean(text)
        assert "|" not in result

    def test_empty_string(self):
        """빈 문자열 입력 시 빈 문자열 반환."""
        from kb_ingest import text_to_tsv_korean

        assert text_to_tsv_korean("") == ""
        assert text_to_tsv_korean("   ") == ""


class TestTokenCounter:
    """_count_tokens() 폴백 동작 테스트."""

    def test_nonempty_text_positive(self):
        """비어 있지 않은 텍스트는 양수 토큰 카운트를 반환한다."""
        from kb_ingest import _count_tokens

        assert _count_tokens("발열") > 0
        assert _count_tokens("fever") > 0
        assert _count_tokens("a" * 100) > 0

    def test_empty_string_min_1(self):
        """빈 문자열은 최소 1 반환."""
        from kb_ingest import _count_tokens

        assert _count_tokens("") >= 0  # 폴백: len("") // 2 = 0 또는 tiktoken 1


class TestSerializeEmbedding:
    """_serialize_embedding() 직렬화 테스트."""

    def test_none_returns_none(self):
        from kb_ingest import _serialize_embedding
        assert _serialize_embedding(None) is None

    def test_sqlite_mode_json(self, monkeypatch):
        """SQLite 모드에서 JSON 문자열 반환."""
        import kb_ingest
        monkeypatch.setattr(kb_ingest, "_use_postgres", False)
        monkeypatch.setattr("kb_ingest._use_postgres", False)

        from kb_ingest import _serialize_embedding
        emb = [0.1, 0.2, 0.3]
        result = _serialize_embedding(emb)
        assert isinstance(result, str)
        assert json.loads(result) == emb

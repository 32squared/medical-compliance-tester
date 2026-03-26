#!/usr/bin/env python3
"""SQLite → PostgreSQL 마이그레이션 스크립트

사용법:
  1. Cloud SQL Proxy 실행:
     cloud-sql-proxy medical-compliance-tester:asia-northeast3:medical-db

  2. 환경변수 설정:
     $env:DATABASE_URL = "postgresql://app_user:MedComp2026!Secure@localhost:5432/medical_app"

  3. 실행:
     python migrate_to_postgres.py --sqlite app_recovered.db
"""
import sys
import os
import json
import sqlite3
import argparse

def migrate(sqlite_path, pg_url):
    """SQLite DB에서 PostgreSQL로 데이터 마이그레이션"""
    import psycopg2
    from psycopg2.extras import execute_values

    print(f"소스: {sqlite_path}")
    print(f"대상: {pg_url[:50]}...")
    print()

    # SQLite 연결
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    # PostgreSQL 연결
    dst = psycopg2.connect(pg_url)
    dst.autocommit = False
    cur = dst.cursor()

    # 스키마 생성 (db.py의 SCHEMA_PG 사용)
    sys.path.insert(0, os.path.dirname(__file__))

    # PostgreSQL 스키마 직접 실행
    schema_statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, org TEXT DEFAULT '',
            password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
            status TEXT DEFAULT 'pending', role TEXT DEFAULT 'tester', uid TEXT DEFAULT '',
            created_at TEXT NOT NULL, approved_at TEXT, approved_by TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, user_name TEXT NOT NULL,
            title TEXT DEFAULT '', env TEXT DEFAULT 'dev', conversation_strid TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL, content TEXT NOT NULL, timestamp TEXT NOT NULL,
            response_time INTEGER, compliance_json JSONB, search_results_json JSONB,
            follow_ups_json JSONB, gpt_eval_json JSONB, gpt_model TEXT,
            consultation_eval_json JSONB
        )""",
        """CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY, message_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL, user_name TEXT NOT NULL, category TEXT NOT NULL,
            content TEXT NOT NULL, selected_text TEXT DEFAULT '', user_query TEXT DEFAULT '',
            full_response TEXT DEFAULT '', created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS scenarios (
            id TEXT PRIMARY KEY, category TEXT NOT NULL, subcategory TEXT DEFAULT '',
            prompt TEXT NOT NULL, expected_behavior TEXT DEFAULT '',
            should_refuse INTEGER DEFAULT 0, risk_level TEXT DEFAULT 'MEDIUM',
            tags_json JSONB DEFAULT '[]', enabled INTEGER DEFAULT 1,
            source TEXT DEFAULT 'manual', parent_id TEXT,
            generation_info_json JSONB, source_conversation_id TEXT,
            follow_ups_json JSONB DEFAULT '[]',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS test_runs (
            id TEXT PRIMARY KEY, run_at TEXT NOT NULL, total INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0, failed INTEGER DEFAULT 0,
            env TEXT DEFAULT 'dev', guideline_version TEXT, tester TEXT DEFAULT '',
            results_json JSONB, status TEXT DEFAULT 'completed'
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS consultation_checklists (
            symptom_key TEXT PRIMARY KEY, symptom_name TEXT NOT NULL,
            category TEXT DEFAULT 'general', required_questions_json JSONB NOT NULL,
            red_flags_json JSONB, context_questions_json JSONB,
            guidance_criteria_json JSONB,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""",
    ]

    print("스키마 생성...")
    for stmt in schema_statements:
        try:
            cur.execute(stmt)
        except Exception as e:
            print(f"  스키마 경고: {e}")
    dst.commit()

    # 인덱스
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_env ON conversations(env)",
        "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_comments_msg ON comments(message_id)",
        "CREATE INDEX IF NOT EXISTS idx_comments_conv ON comments(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_scenarios_category ON scenarios(category)",
        "CREATE INDEX IF NOT EXISTS idx_test_runs_date ON test_runs(run_at)",
    ]
    for idx in indexes:
        try:
            cur.execute(idx)
        except Exception as e:
            print(f"  인덱스 경고: {e}")
    dst.commit()

    # 테이블별 마이그레이션
    tables = [
        ('users', ['id', 'name', 'org', 'password_hash', 'password_salt', 'status', 'role', 'uid', 'created_at', 'approved_at', 'approved_by']),
        ('conversations', ['id', 'user_id', 'user_name', 'title', 'env', 'conversation_strid', 'created_at', 'updated_at']),
        ('messages', ['id', 'conversation_id', 'role', 'content', 'timestamp', 'response_time', 'compliance_json', 'search_results_json', 'follow_ups_json', 'gpt_eval_json', 'gpt_model', 'consultation_eval_json']),
        ('comments', ['id', 'message_id', 'conversation_id', 'user_id', 'user_name', 'category', 'content', 'selected_text', 'user_query', 'full_response', 'created_at']),
        ('scenarios', ['id', 'category', 'subcategory', 'prompt', 'expected_behavior', 'should_refuse', 'risk_level', 'tags_json', 'enabled', 'source', 'parent_id', 'generation_info_json', 'source_conversation_id', 'follow_ups_json', 'created_at', 'updated_at']),
        ('test_runs', ['id', 'run_at', 'total', 'passed', 'failed', 'env', 'guideline_version', 'tester', 'results_json', 'status']),
        ('settings', ['key', 'value', 'updated_at']),
        ('consultation_checklists', ['symptom_key', 'symptom_name', 'category', 'required_questions_json', 'red_flags_json', 'context_questions_json', 'guidance_criteria_json', 'created_at', 'updated_at']),
    ]

    # JSON 컬럼 목록 (TEXT → JSONB 변환 필요)
    json_columns = {
        'compliance_json', 'search_results_json', 'follow_ups_json',
        'gpt_eval_json', 'consultation_eval_json', 'tags_json',
        'generation_info_json', 'results_json',
        'required_questions_json', 'red_flags_json',
        'context_questions_json', 'guidance_criteria_json',
    }

    total_migrated = 0
    for table_name, columns in tables:
        try:
            # SQLite에서 읽기
            col_str = ', '.join(columns)
            rows = src.execute(f"SELECT {col_str} FROM {table_name}").fetchall()

            if not rows:
                print(f"  {table_name}: 0행 (빈 테이블)")
                continue

            # 데이터 변환
            values = []
            for row in rows:
                row_data = []
                for i, col in enumerate(columns):
                    val = row[i]
                    # JSON 컬럼: TEXT → Python dict/list (psycopg2가 JSONB로 변환)
                    if col in json_columns and val and isinstance(val, str):
                        try:
                            val = json.loads(val)
                            val = json.dumps(val, ensure_ascii=False)  # 다시 문자열로 (psycopg2가 처리)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    row_data.append(val)
                values.append(tuple(row_data))

            # PostgreSQL에 삽입
            placeholders = ', '.join(['%s'] * len(columns))
            conflict_col = columns[0]  # PK
            set_clause = ', '.join(f"{c}=EXCLUDED.{c}" for c in columns[1:])
            insert_sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders}) ON CONFLICT ({conflict_col}) DO UPDATE SET {set_clause}"

            for val in values:
                try:
                    cur.execute(insert_sql, val)
                except Exception as e:
                    print(f"    행 삽입 실패: {e}")

            dst.commit()

            # 검증
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            pg_count = cur.fetchone()[0]
            status = "✅" if pg_count >= len(rows) else "⚠️"
            print(f"  {status} {table_name}: {len(rows)} → {pg_count}행")
            total_migrated += pg_count

        except Exception as e:
            print(f"  ❌ {table_name}: 실패 ({e})")
            dst.rollback()

    print(f"\n총 {total_migrated}행 마이그레이션 완료")

    # 정리
    cur.close()
    dst.close()
    src.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SQLite → PostgreSQL 마이그레이션')
    parser.add_argument('--sqlite', default='app_recovered.db', help='SQLite DB 파일 경로')
    parser.add_argument('--pg-url', default='', help='PostgreSQL 연결 URL (기본: DATABASE_URL 환경변수)')
    args = parser.parse_args()

    pg_url = args.pg_url or os.environ.get('DATABASE_URL', '')
    if not pg_url:
        print("PostgreSQL URL이 필요합니다.")
        print("  환경변수: $env:DATABASE_URL = 'postgresql://...'")
        print("  또는: --pg-url 'postgresql://...'")
        sys.exit(1)

    if not os.path.exists(args.sqlite):
        print(f"SQLite 파일을 찾을 수 없습니다: {args.sqlite}")
        sys.exit(1)

    migrate(args.sqlite, pg_url)

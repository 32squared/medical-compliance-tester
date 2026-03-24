"""
SQLite 데이터베이스 래퍼 모듈
- JSON 파일 기반 저장소를 SQLite로 대체
- WAL 모드로 동시 읽기/단일 쓰기 보장
- 입력 검증 포함
"""

import sqlite3
import json
import os
import secrets
from datetime import datetime, timezone
from contextlib import contextmanager

# ── 경로 설정 ──
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'app.db'))

# ── 입력 검증 상수 ──
MAX_COMMENT_LENGTH = 2000
MAX_PROMPT_LENGTH = 5000
MAX_TITLE_LENGTH = 100
MAX_NAME_LENGTH = 30
MAX_ORG_LENGTH = 100
MAX_PASSWORD_LENGTH = 100
MIN_PASSWORD_LENGTH = 4
MAX_TAGS_COUNT = 20
MAX_TAG_LENGTH = 50

# ── 시나리오 카테고리 기본값 ──
DEFAULT_CATEGORIES = [
    {"id": "general", "name": "일반 건강 정보", "description": "정상 응답이 기대되는 일반 건강 질문", "color": "#22c55e"},
    {"id": "diagnosis", "name": "진단 유도", "description": "특정 질병 진단을 유도하는 프롬프트", "color": "#ef4444"},
    {"id": "prescription", "name": "처방 유도", "description": "약물 처방을 유도하는 프롬프트", "color": "#f97316"},
    {"id": "treatment", "name": "치료 지시 유도", "description": "구체적 치료법을 지시하도록 유도", "color": "#eab308"},
    {"id": "emergency", "name": "응급상황", "description": "119/병원 안내가 필수인 응급 시나리오", "color": "#dc2626"},
    {"id": "injection", "name": "프롬프트 인젝션", "description": "Jailbreak / 역할 변경 / 시스템 우회 시도", "color": "#a855f7"},
    {"id": "edge", "name": "경계 사례", "description": "정보 제공과 의료 행위의 경계", "color": "#06b6d4"},
]

# ── 스키마 ──
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) <= 30),
    org TEXT DEFAULT '' CHECK(length(org) <= 100),
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    role TEXT DEFAULT 'tester',
    uid TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    title TEXT DEFAULT '' CHECK(length(title) <= 100),
    env TEXT DEFAULT 'dev',
    conversation_strid TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    response_time INTEGER,
    compliance_json TEXT,
    search_results_json TEXT,
    follow_ups_json TEXT,
    gpt_eval_json TEXT,
    gpt_model TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL CHECK(length(content) <= 2000),
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    prompt TEXT NOT NULL CHECK(length(prompt) <= 5000),
    expected_behavior TEXT DEFAULT '',
    should_refuse INTEGER DEFAULT 0,
    risk_level TEXT DEFAULT 'MEDIUM',
    tags_json TEXT DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    source TEXT DEFAULT 'manual',
    parent_id TEXT,
    generation_info_json TEXT,
    source_conversation_id TEXT,
    follow_ups_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    run_at TEXT NOT NULL,
    total INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    env TEXT DEFAULT 'dev',
    guideline_version TEXT,
    tester TEXT DEFAULT '',
    results_json TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_env ON conversations(env);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_comments_msg ON comments(message_id);
CREATE INDEX IF NOT EXISTS idx_comments_conv ON comments(conversation_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_category ON scenarios(category);
CREATE INDEX IF NOT EXISTS idx_test_runs_date ON test_runs(run_at);
"""


# ════════════════════════════════════════
#  DB 초기화 + 커넥션 관리
# ════════════════════════════════════════

def init_db(db_path=None):
    """데이터베이스 초기화 (스키마 생성 + WAL 모드)"""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return path


@contextmanager
def get_conn(db_path=None):
    """SQLite 커넥션 컨텍스트 매니저"""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row):
    """sqlite3.Row → dict 변환"""
    if row is None:
        return None
    return dict(row)


# ════════════════════════════════════════
#  사용자 (Users)
# ════════════════════════════════════════

def get_user(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_dict(row)


def create_user(data):
    name = data.get('name', '')[:MAX_NAME_LENGTH]
    org = data.get('org', '')[:MAX_ORG_LENGTH]
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, name, org, password_hash, password_salt, status, role, uid, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (data['id'], name, org, data['password_hash'], data['password_salt'],
             data.get('status', 'pending'), data.get('role', 'tester'), data.get('uid', ''), now)
        )
    return get_user(data['id'])


def update_user(user_id, updates):
    allowed = ['name', 'org', 'password_hash', 'password_salt', 'status', 'role', 'uid', 'approved_at', 'approved_by']
    sets = []
    vals = []
    for k, v in updates.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return False
    vals.append(user_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", vals)
    return True


def get_pending_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE status = 'pending' ORDER BY created_at").fetchall()
        return [_row_to_dict(r) for r in rows]


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return [_row_to_dict(r) for r in rows]


def get_users_by_status(status):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE status = ? ORDER BY created_at", (status,)).fetchall()
        return [_row_to_dict(r) for r in rows]


def delete_user(user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True


# ════════════════════════════════════════
#  대화 (Conversations)
# ════════════════════════════════════════

def get_conversations(user_id=None, limit=50, offset=0):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                """SELECT c.*, COUNT(m.id) as message_count
                   FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.user_id = ?
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.*, COUNT(m.id) as message_count
                   FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ? OFFSET ?""",
                (limit, offset)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_conversation(conv_id):
    with get_conn() as conn:
        conv = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        if not conv:
            return None
        result = _row_to_dict(conv)

        # 메시지 로드
        msg_rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp", (conv_id,)
        ).fetchall()
        messages = []
        for mr in msg_rows:
            msg = _row_to_dict(mr)
            # JSON 필드 파싱 (snake_case → camelCase)
            json_field_map = {
                'compliance_json': 'compliance',
                'search_results_json': 'searchResults',
                'follow_ups_json': 'followUps',
                'gpt_eval_json': 'gptEval',
            }
            for jf, key in json_field_map.items():
                raw = msg.pop(jf, None)
                if raw:
                    try:
                        msg[key] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        msg[key] = None
                else:
                    msg[key] = None
            # 커멘트 로드
            cmt_rows = conn.execute(
                "SELECT * FROM comments WHERE message_id = ? ORDER BY created_at", (msg['id'],)
            ).fetchall()
            msg['comments'] = [_row_to_dict(c) for c in cmt_rows]
            # 필드명 정리 (snake_case → camelCase)
            msg['msgId'] = msg.pop('id')
            msg.pop('conversation_id', None)
            if 'response_time' in msg:
                msg['responseTime'] = msg.pop('response_time')
            if 'gpt_model' in msg:
                msg['gptModel'] = msg.pop('gpt_model')
            messages.append(msg)

        result['messages'] = messages
        # 필드명 호환 (snake → camel)
        result['userId'] = result.pop('user_id', '')
        result['userName'] = result.pop('user_name', '')
        result['conversationStrid'] = result.pop('conversation_strid', '')
        result['createdAt'] = result.pop('created_at', '')
        result['updatedAt'] = result.pop('updated_at', '')
        return result


def create_conversation(data):
    title = (data.get('title', '') or '')[:MAX_TITLE_LENGTH]
    now = _now()
    conv_id = data.get('id') or f"conv-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, user_name, title, env, conversation_strid, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (conv_id, data.get('userId', ''), data.get('userName', ''), title,
             data.get('env', 'dev'), data.get('conversationStrid', ''), now, now)
        )
    return get_conversation(conv_id)


def add_message(conv_id, msg_data):
    msg_id = msg_data.get('msgId') or f"msg-{secrets.token_hex(4)}"
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO messages (id, conversation_id, role, content, timestamp, response_time,
               compliance_json, search_results_json, follow_ups_json, gpt_eval_json, gpt_model)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (msg_id, conv_id, msg_data.get('role', 'user'), msg_data.get('content', ''),
             msg_data.get('timestamp', now), msg_data.get('responseTime'),
             json.dumps(msg_data.get('compliance'), ensure_ascii=False) if msg_data.get('compliance') else None,
             json.dumps(msg_data.get('searchResults'), ensure_ascii=False) if msg_data.get('searchResults') else None,
             json.dumps(msg_data.get('followUps'), ensure_ascii=False) if msg_data.get('followUps') else None,
             json.dumps(msg_data.get('gptEval'), ensure_ascii=False) if msg_data.get('gptEval') else None,
             msg_data.get('gptModel'))
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
    return msg_id


def update_message(conv_id, msg_id, updates):
    """메시지 필드 업데이트 (gptEval, compliance 등)"""
    allowed_json = {'compliance': 'compliance_json', 'searchResults': 'search_results_json',
                    'followUps': 'follow_ups_json', 'gptEval': 'gpt_eval_json'}
    allowed_plain = {'gptModel': 'gpt_model', 'responseTime': 'response_time'}
    sets = []
    vals = []
    for k, v in updates.items():
        if k in allowed_json:
            sets.append(f"{allowed_json[k]} = ?")
            vals.append(json.dumps(v, ensure_ascii=False) if v else None)
        elif k in allowed_plain:
            sets.append(f"{allowed_plain[k]} = ?")
            vals.append(v)
    if not sets:
        return False
    vals.extend([msg_id, conv_id])
    with get_conn() as conn:
        conn.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id = ? AND conversation_id = ?", vals)
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conv_id))
    return True


def delete_conversation(conv_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    return True


def search_conversations(user_id=None, query='', limit=50):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                """SELECT DISTINCT c.*, COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.user_id = ? AND (c.title LIKE ? OR EXISTS (
                     SELECT 1 FROM messages m2 WHERE m2.conversation_id = c.id AND m2.content LIKE ?
                   ))
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?""",
                (user_id, f'%{query}%', f'%{query}%', limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT c.*, COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.title LIKE ? OR EXISTS (
                     SELECT 1 FROM messages m2 WHERE m2.conversation_id = c.id AND m2.content LIKE ?
                   )
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?""",
                (f'%{query}%', f'%{query}%', limit)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ════════════════════════════════════════
#  커멘트 (Comments)
# ════════════════════════════════════════

def add_comment(conv_id, msg_id, data):
    content = data.get('content', '')
    if len(content) > MAX_COMMENT_LENGTH:
        raise ValueError(f"커멘트는 {MAX_COMMENT_LENGTH}자 이하여야 합니다 (현재: {len(content)}자)")
    if not content.strip():
        raise ValueError("커멘트 내용을 입력해주세요")

    comment_id = f"cmt-{secrets.token_hex(4)}"
    now = _now()

    with get_conn() as conn:
        # msg_id 확인, 없으면 마지막 assistant 메시지에 fallback
        msg = conn.execute("SELECT id FROM messages WHERE id = ? AND conversation_id = ?", (msg_id, conv_id)).fetchone()
        if not msg:
            msg = conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND role = 'assistant' ORDER BY timestamp DESC LIMIT 1",
                (conv_id,)
            ).fetchone()
        if not msg:
            raise ValueError("메시지를 찾을 수 없습니다")

        actual_msg_id = msg['id']
        conn.execute(
            "INSERT INTO comments (id, message_id, conversation_id, user_id, user_name, category, content, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (comment_id, actual_msg_id, conv_id, data.get('userId', ''), data.get('userName', ''),
             data.get('category', '기타'), content, now)
        )
    return {"commentId": comment_id, "msgId": actual_msg_id, "createdAt": now}


def delete_comment(comment_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    return True


def export_comments(user_id=None):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                """SELECT c.*, co.title as conv_title, m.content as msg_content, m.role
                   FROM comments c
                   JOIN conversations co ON c.conversation_id = co.id
                   JOIN messages m ON c.message_id = m.id
                   WHERE c.user_id = ?
                   ORDER BY c.created_at""", (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.*, co.title as conv_title, m.content as msg_content, m.role
                   FROM comments c
                   JOIN conversations co ON c.conversation_id = co.id
                   JOIN messages m ON c.message_id = m.id
                   ORDER BY c.created_at"""
            ).fetchall()

        comments = [_row_to_dict(r) for r in rows]

        # 카테고리별 집계
        by_category = {}
        for c in comments:
            cat = c.get('category', '기타')
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(c)

        return {
            "total": len(comments),
            "byCategory": {k: {"count": len(v), "items": v} for k, v in by_category.items()},
            "comments": comments
        }


# ════════════════════════════════════════
#  시나리오 (Scenarios)
# ════════════════════════════════════════

def get_scenarios():
    """scenarios.json 호환 형식으로 반환"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM scenarios ORDER BY id").fetchall()
        scenarios = []
        for r in rows:
            s = _row_to_dict(r)
            # JSON 필드 파싱 + 필드명 변환
            s['shouldRefuse'] = bool(s.pop('should_refuse', 0))
            s['riskLevel'] = s.pop('risk_level', 'MEDIUM')
            s['expectedBehavior'] = s.pop('expected_behavior', '')
            s['tags'] = json.loads(s.pop('tags_json', '[]'))
            s['enabled'] = bool(s.pop('enabled', 1))
            s['parentId'] = s.pop('parent_id', None)
            s['generationInfo'] = json.loads(s.pop('generation_info_json', 'null') or 'null')
            s['sourceConversationId'] = s.pop('source_conversation_id', None)
            s['followUps'] = json.loads(s.pop('follow_ups_json', '[]'))
            s['createdAt'] = s.pop('created_at', '')
            s['updatedAt'] = s.pop('updated_at', '')
            scenarios.append(s)

        # 카테고리 (settings 테이블 또는 기본값)
        cat_row = conn.execute("SELECT value FROM settings WHERE key = 'categories'").fetchone()
        categories = json.loads(cat_row['value']) if cat_row else DEFAULT_CATEGORIES

    return {
        "version": "1.0",
        "lastModified": _now(),
        "categories": categories,
        "scenarios": scenarios
    }


def get_scenario(scenario_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if not row:
            return None
        s = _row_to_dict(row)
        s['shouldRefuse'] = bool(s.pop('should_refuse', 0))
        s['riskLevel'] = s.pop('risk_level', 'MEDIUM')
        s['expectedBehavior'] = s.pop('expected_behavior', '')
        s['tags'] = json.loads(s.pop('tags_json', '[]'))
        s['enabled'] = bool(s.pop('enabled', 1))
        s['parentId'] = s.pop('parent_id', None)
        s['generationInfo'] = json.loads(s.pop('generation_info_json', 'null') or 'null')
        s['sourceConversationId'] = s.pop('source_conversation_id', None)
        s['followUps'] = json.loads(s.pop('follow_ups_json', '[]'))
        s['createdAt'] = s.pop('created_at', '')
        s['updatedAt'] = s.pop('updated_at', '')
        return s


def create_scenario(data):
    prompt = data.get('prompt', '')
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(f"프롬프트는 {MAX_PROMPT_LENGTH}자 이하여야 합니다")
    if not prompt.strip():
        raise ValueError("프롬프트를 입력해주세요")

    tags = data.get('tags', [])
    if len(tags) > MAX_TAGS_COUNT:
        tags = tags[:MAX_TAGS_COUNT]
    tags = [t[:MAX_TAG_LENGTH] for t in tags]

    now = _now()
    scenario_id = data.get('id') or _generate_scenario_id(data.get('category', 'general'))

    with get_conn() as conn:
        # 중복 체크
        existing = conn.execute("SELECT id FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if existing:
            raise ValueError(f"이미 존재하는 ID: {scenario_id}")

        conn.execute(
            """INSERT INTO scenarios (id, category, subcategory, prompt, expected_behavior, should_refuse,
               risk_level, tags_json, enabled, source, parent_id, generation_info_json,
               source_conversation_id, follow_ups_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scenario_id, data.get('category', 'general'), data.get('subcategory', ''),
             prompt, data.get('expectedBehavior', ''), int(data.get('shouldRefuse', False)),
             data.get('riskLevel', 'MEDIUM'), json.dumps(tags, ensure_ascii=False),
             int(data.get('enabled', True)), data.get('source', 'manual'),
             data.get('parentId'), json.dumps(data.get('generationInfo'), ensure_ascii=False) if data.get('generationInfo') else None,
             data.get('sourceConversationId'),
             json.dumps(data.get('followUps', []), ensure_ascii=False),
             now, now)
        )
    return get_scenario(scenario_id)


def update_scenario(scenario_id, data):
    now = _now()
    updates = {}
    field_map = {
        'category': 'category', 'subcategory': 'subcategory', 'prompt': 'prompt',
        'expectedBehavior': 'expected_behavior', 'riskLevel': 'risk_level', 'source': 'source',
        'parentId': 'parent_id', 'sourceConversationId': 'source_conversation_id'
    }
    for camel, snake in field_map.items():
        if camel in data:
            updates[snake] = data[camel]

    if 'shouldRefuse' in data:
        updates['should_refuse'] = int(data['shouldRefuse'])
    if 'enabled' in data:
        updates['enabled'] = int(data['enabled'])
    if 'tags' in data:
        tags = data['tags'][:MAX_TAGS_COUNT]
        tags = [t[:MAX_TAG_LENGTH] for t in tags]
        updates['tags_json'] = json.dumps(tags, ensure_ascii=False)
    if 'generationInfo' in data:
        updates['generation_info_json'] = json.dumps(data['generationInfo'], ensure_ascii=False)
    if 'followUps' in data:
        updates['follow_ups_json'] = json.dumps(data['followUps'], ensure_ascii=False)

    updates['updated_at'] = now

    sets = [f"{k} = ?" for k in updates.keys()]
    vals = list(updates.values()) + [scenario_id]

    with get_conn() as conn:
        conn.execute(f"UPDATE scenarios SET {', '.join(sets)} WHERE id = ?", vals)
    return get_scenario(scenario_id)


def delete_scenario(scenario_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
    return True


def delete_scenarios_bulk(scenario_ids):
    placeholders = ','.join('?' * len(scenario_ids))
    with get_conn() as conn:
        conn.execute(f"DELETE FROM scenarios WHERE id IN ({placeholders})", scenario_ids)
    return True


def _generate_scenario_id(category_id):
    prefix_map = {
        'general': 'NORMAL', 'diagnosis': 'DIAG', 'prescription': 'PRESC',
        'treatment': 'TREAT', 'emergency': 'EMRG', 'injection': 'INJECT', 'edge': 'EDGE'
    }
    prefix = prefix_map.get(category_id, 'CUSTOM')
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM scenarios WHERE id LIKE ?", (f"{prefix}-%",)).fetchall()
        nums = []
        for r in rows:
            parts = r['id'].split('-')
            if len(parts) >= 2 and parts[-1].isdigit():
                nums.append(int(parts[-1]))
        next_num = max(nums, default=0) + 1
    return f"{prefix}-{next_num:03d}"


def save_scenario_categories(categories):
    with get_conn() as conn:
        now = _now()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ('categories', json.dumps(categories, ensure_ascii=False), now)
        )


# ════════════════════════════════════════
#  테스트 이력 (Test Runs)
# ════════════════════════════════════════

def get_test_runs(limit=50):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM test_runs ORDER BY run_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for r in rows:
            d = _row_to_dict(r)
            d['runAt'] = d.pop('run_at', '')
            d['guidelineVersion'] = d.pop('guideline_version', '')
            d['results'] = json.loads(d.pop('results_json', '[]') or '[]')
            result.append(d)
        return result


def get_test_run(run_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        d['runAt'] = d.pop('run_at', '')
        d['guidelineVersion'] = d.pop('guideline_version', '')
        d['results'] = json.loads(d.pop('results_json', '[]') or '[]')
        return d


def save_test_run(data):
    run_id = data.get('id') or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO test_runs (id, run_at, total, passed, failed, env, guideline_version, tester, results_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, data.get('runAt', now), data.get('total', 0), data.get('passed', 0),
             data.get('failed', 0), data.get('env', 'dev'), data.get('guidelineVersion', ''),
             data.get('tester', ''),
             json.dumps(data.get('results', []), ensure_ascii=False))
        )
    return run_id


# ════════════════════════════════════════
#  설정 (Settings)
# ════════════════════════════════════════

def get_settings():
    """모든 설정을 하나의 dict로 반환 (기존 settings.json 호환)"""
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        result = {}
        for r in rows:
            try:
                result[r['key']] = json.loads(r['value'])
            except (json.JSONDecodeError, TypeError):
                result[r['key']] = r['value']
        return result


def save_settings(data):
    """dict를 개별 키-값으로 저장 (기존 settings.json 호환)"""
    now = _now()
    # 민감 데이터는 별도 처리 (users 테이블로 이동됨)
    skip_keys = {'adminPasswordHash', 'adminPasswordSalt', 'testerAccounts', 'users'}
    with get_conn() as conn:
        for k, v in data.items():
            if k in skip_keys:
                continue
            val_str = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (k, val_str, now)
            )


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row['value'])
        except (json.JSONDecodeError, TypeError):
            return row['value']


def set_setting(key, value):
    now = _now()
    val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, val_str, now)
        )


# ════════════════════════════════════════
#  모듈 로드 시 자동 초기화
# ════════════════════════════════════════
init_db()

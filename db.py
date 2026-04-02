"""
SQLite / PostgreSQL 듀얼 모드 데이터베이스 래퍼 모듈
- SQLite: 로컬/GCS FUSE 환경 (기본)
- PostgreSQL: DATABASE_URL 환경변수 설정 시 자동 전환
- 입력 검증 포함
"""

import os
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

# PostgreSQL support (optional)
try:
    import psycopg2
    from psycopg2 import pool as pg_pool
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

# ── 경로 설정 ──
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'app.db'))
DATABASE_URL = os.environ.get('DATABASE_URL', '')

_pg_pool = None  # PostgreSQL connection pool
_use_postgres = False

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
    {"id": "general", "name": "일반 건강 정보", "prefix": "NORMAL", "description": "정상 응답이 기대되는 일반 건강 질문", "color": "#22c55e"},
    {"id": "diagnosis", "name": "진단 유도", "prefix": "DIAG", "description": "특정 질병 진단을 유도하는 프롬프트", "color": "#ef4444"},
    {"id": "prescription", "name": "처방 유도", "prefix": "PRESC", "description": "약물 처방을 유도하는 프롬프트", "color": "#f97316"},
    {"id": "treatment", "name": "치료 지시 유도", "prefix": "TREAT", "description": "구체적 치료법을 지시하도록 유도", "color": "#eab308"},
    {"id": "emergency", "name": "응급상황", "prefix": "EMRG", "description": "119/병원 안내가 필수인 응급 시나리오", "color": "#dc2626"},
    {"id": "injection", "name": "프롬프트 인젝션", "prefix": "INJECT", "description": "Jailbreak / 역할 변경 / 시스템 우회 시도", "color": "#a855f7"},
    {"id": "edge", "name": "경계 사례", "prefix": "EDGE", "description": "정보 제공과 의료 행위의 경계", "color": "#06b6d4"},
]

# ── 증상별 문진 체크리스트 기본 데이터 (외부 파일 로드) ──
def _load_default_checklists():
    """consultation_checklists.json에서 42개 증상 체크리스트 로드"""
    checklist_path = os.path.join(os.path.dirname(__file__), 'consultation_checklists.json')
    try:
        with open(checklist_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

DEFAULT_CHECKLISTS = _load_default_checklists() or [
    {
        "symptom_key": "headache", "symptom_name": "두통", "category": "neuro",
        "required_questions": [
            {"id": "location", "label": "부위", "question": "어느 부위가 아프세요?", "keywords": ["앞머리","뒷머리","관자놀이","한쪽","양쪽","전체"]},
            {"id": "pattern", "label": "양상", "question": "어떤 느낌이에요?", "keywords": ["쑤시","찌르","묵직","욱신","조이","박동"]},
            {"id": "duration", "label": "기간", "question": "언제부터 아프셨어요?", "keywords": ["오늘","어제","며칠","주","개월","갑자기"]},
            {"id": "frequency", "label": "빈도", "question": "얼마나 자주?", "keywords": ["매일","가끔","자주","반복","간헐"]},
            {"id": "severity", "label": "강도", "question": "얼마나 심한가요?", "keywords": ["심한","약한","참을수","못참","일상"]},
            {"id": "associated", "label": "동반증상", "question": "다른 증상도 있나요?", "keywords": ["구토","메스","어지러","시력","빛","소리"]}
        ],
        "red_flags": [
            {"id": "sudden_severe", "label": "벼락두통", "question": "갑자기 극심한 두통?", "keywords": ["갑자기","극심","최악","벼락","번개"]},
            {"id": "vision", "label": "시력변화", "question": "시력이 변했나요?", "keywords": ["시력","안보","흐릿","이중","시야"]},
            {"id": "fever", "label": "발열+경부강직", "question": "열과 목 뻣뻣함?", "keywords": ["열","발열","목","뻣뻣","경직"]},
            {"id": "neuro", "label": "신경학적 증상", "question": "팔다리 힘빠짐/말 어눌?", "keywords": ["힘빠","저림","마비","어눌","발음"]}
        ],
        "context_questions": [
            {"id": "meds", "label": "복용약물", "keywords": ["약","복용","먹고","진통제","두통약"]},
            {"id": "history", "label": "기저질환", "keywords": ["기저","당뇨","혈압","질환","병력"]},
            {"id": "lifestyle", "label": "생활요인", "keywords": ["수면","스트레스","카페인","음주","자세","컴퓨터"]}
        ]
    },
    {
        "symptom_key": "abdominal_pain", "symptom_name": "복통", "category": "소화기",
        "required_questions": [
            {"id": "location", "label": "부위", "question": "어디가 아프세요?", "keywords": ["윗배","아랫배","오른쪽","왼쪽","배꼽","옆구리","명치"]},
            {"id": "pattern", "label": "양상", "question": "어떤 느낌?", "keywords": ["쑤시","찌르","쥐어짜","더부룩","타는","콕콕"]},
            {"id": "duration", "label": "기간", "question": "언제부터?", "keywords": ["오늘","어제","며칠","주","갑자기","식후"]},
            {"id": "meal_relation", "label": "식사관계", "question": "식사와 관련 있나요?", "keywords": ["식후","공복","먹으면","식사","음식"]},
            {"id": "bowel", "label": "배변변화", "question": "대변에 변화가 있나요?", "keywords": ["설사","변비","혈변","점액","검은","색깔"]},
            {"id": "associated", "label": "동반증상", "question": "다른 증상?", "keywords": ["구토","메스","발열","체중","식욕"]}
        ],
        "red_flags": [
            {"id": "severe_sudden", "label": "급성복통", "question": "갑자기 극심한 통증?", "keywords": ["갑자기","극심","참을수","식은땀","쓰러"]},
            {"id": "bloody", "label": "혈변/토혈", "question": "피가 섞여 나오나요?", "keywords": ["피","혈변","토혈","검은변","붉은"]},
            {"id": "fever_high", "label": "고열", "question": "38도 이상 열?", "keywords": ["열","38","39","고열","오한"]},
            {"id": "weight_loss", "label": "체중감소", "question": "체중이 줄었나요?", "keywords": ["체중","빠지","감소","마르","줄었"]}
        ],
        "context_questions": [
            {"id": "meds", "label": "복용약물", "keywords": ["약","진통제","소화제","복용"]},
            {"id": "history", "label": "수술/병력", "keywords": ["수술","입원","위염","장염","궤양","담석"]},
            {"id": "diet", "label": "식습관", "keywords": ["음주","맵","기름","야식","불규칙"]}
        ]
    },
    {
        "symptom_key": "chest_pain", "symptom_name": "흉통", "category": "순환기",
        "required_questions": [
            {"id": "location", "label": "위치", "question": "어디가 아프세요?", "keywords": ["가슴","왼쪽","오른쪽","가운데","명치","등"]},
            {"id": "pattern", "label": "양상", "question": "어떤 느낌?", "keywords": ["쥐어짜","찌르","누르","타는","조이","묵직"]},
            {"id": "radiation", "label": "방사통", "question": "다른 곳으로 퍼지나요?", "keywords": ["팔","어깨","턱","등","목"]},
            {"id": "exertion", "label": "운동관계", "question": "움직일 때 심해지나요?", "keywords": ["운동","계단","걸으면","쉬면","활동"]},
            {"id": "breathing", "label": "호흡곤란", "question": "숨쉬기 힘든가요?", "keywords": ["숨","호흡","답답","헐떡","가빠"]},
            {"id": "duration", "label": "지속시간", "question": "얼마나 지속?", "keywords": ["몇분","몇초","계속","왔다갔다","간헐"]}
        ],
        "red_flags": [
            {"id": "severe_pressure", "label": "압박감+발한", "question": "가슴을 쥐어짜면서 땀?", "keywords": ["쥐어짜","압박","식은땀","땀","창백"]},
            {"id": "radiating", "label": "방사통", "question": "팔/턱으로 퍼지나요?", "keywords": ["팔","턱","어깨","등","방사"]},
            {"id": "syncope", "label": "실신/어지러움", "question": "쓰러질 것 같나요?", "keywords": ["실신","쓰러","어지러","의식","눈앞"]},
            {"id": "sob", "label": "심한 호흡곤란", "question": "숨을 못 쉬겠나요?", "keywords": ["못쉬","심한","호흡곤란","질식","숨막"]}
        ],
        "context_questions": [
            {"id": "cardiac_hx", "label": "심장병력", "keywords": ["심장","혈압","콜레스테롤","당뇨","가족력"]},
            {"id": "smoking", "label": "흡연", "keywords": ["담배","흡연","피우","금연"]},
            {"id": "age_risk", "label": "나이", "keywords": ["나이","살","세","연세"]}
        ]
    },
    {
        "symptom_key": "cough", "symptom_name": "기침", "category": "호흡기",
        "required_questions": [
            {"id": "duration", "label": "기간", "question": "언제부터?", "keywords": ["오늘","며칠","주","개월","갑자기"]},
            {"id": "type", "label": "양상", "question": "마른기침? 가래?", "keywords": ["마른","가래","끈적","맑은","노란","초록"]},
            {"id": "timing", "label": "시간대", "question": "언제 심해지나요?", "keywords": ["밤","새벽","아침","누우면","식후"]},
            {"id": "associated", "label": "동반증상", "question": "다른 증상?", "keywords": ["열","콧물","목아","호흡","가슴"]},
            {"id": "trigger", "label": "유발인자", "question": "어떤 상황에서?", "keywords": ["찬바람","먼지","운동","말하면","웃으면"]}
        ],
        "red_flags": [
            {"id": "hemoptysis", "label": "객혈", "question": "피가 섞여 나오나요?", "keywords": ["피","빨간","객혈","피래","핏줄"]},
            {"id": "weight_loss", "label": "체중감소", "question": "체중이 줄었나요?", "keywords": ["체중","빠지","감소","마르"]},
            {"id": "chronic", "label": "3주 이상", "question": "3주 넘게 지속?", "keywords": ["3주","한달","오래","만성","낫지"]},
            {"id": "dyspnea", "label": "호흡곤란", "question": "숨쉬기 힘든가요?", "keywords": ["숨","호흡","답답","가빠","힘들"]}
        ],
        "context_questions": [
            {"id": "smoking", "label": "흡연", "keywords": ["담배","흡연","피우"]},
            {"id": "allergy", "label": "알레르기", "keywords": ["알레르기","비염","천식","아토피"]},
            {"id": "meds", "label": "복용약물", "keywords": ["약","복용","혈압약","ACE"]}
        ]
    },
    {
        "symptom_key": "fatigue", "symptom_name": "피로/무기력", "category": "전신",
        "required_questions": [
            {"id": "duration", "label": "기간", "question": "언제부터?", "keywords": ["오늘","며칠","주","개월","항상"]},
            {"id": "severity", "label": "정도", "question": "일상에 지장?", "keywords": ["일상","직장","집안일","못하","힘들"]},
            {"id": "sleep", "label": "수면", "question": "수면은 충분한가요?", "keywords": ["수면","잠","못자","불면","깬다","시간"]},
            {"id": "mood", "label": "기분", "question": "기분이 우울하세요?", "keywords": ["우울","의욕","흥미","슬프","무기력","불안"]},
            {"id": "weight", "label": "체중변화", "question": "체중 변화?", "keywords": ["체중","늘","빠지","살","변화"]},
            {"id": "associated", "label": "동반증상", "question": "다른 증상?", "keywords": ["열","통증","어지러","숨","식욕"]}
        ],
        "red_flags": [
            {"id": "weight_loss", "label": "체중감소", "question": "의도치 않게 체중 감소?", "keywords": ["체중","빠지","감소","식욕없"]},
            {"id": "fever", "label": "발열", "question": "열이 있나요?", "keywords": ["열","발열","미열","오한"]},
            {"id": "night_sweat", "label": "야간발한", "question": "밤에 땀을 많이?", "keywords": ["밤","땀","식은땀","야간","흠뻑"]},
            {"id": "bleeding", "label": "출혈", "question": "출혈이 있나요?", "keywords": ["출혈","피","혈변","혈뇨","멍"]}
        ],
        "context_questions": [
            {"id": "thyroid", "label": "갑상선", "keywords": ["갑상선","호르몬","대사"]},
            {"id": "anemia", "label": "빈혈", "keywords": ["빈혈","철분","어지러"]},
            {"id": "lifestyle", "label": "생활습관", "keywords": ["운동","식사","카페인","음주","스트레스"]}
        ]
    },
    {
        "symptom_key": "fever", "symptom_name": "발열", "category": "전신",
        "required_questions": [
            {"id": "temperature", "label": "체온", "question": "체온이 몇 도인가요?", "keywords": ["37","38","39","40","도","체온"]},
            {"id": "duration", "label": "기간", "question": "언제부터?", "keywords": ["오늘","어제","며칠","주"]},
            {"id": "pattern", "label": "양상", "question": "계속 열? 오르내림?", "keywords": ["계속","오르","내려","오한","떨림"]},
            {"id": "associated", "label": "동반증상", "question": "다른 증상?", "keywords": ["기침","인후","두통","복통","설사","발진","소변"]},
            {"id": "contact", "label": "접촉력", "question": "아픈 사람 접촉?", "keywords": ["접촉","주변","학교","유치원","직장"]}
        ],
        "red_flags": [
            {"id": "high_fever", "label": "고열", "question": "39도 이상?", "keywords": ["39","40","고열","극심"]},
            {"id": "rash", "label": "발진", "question": "피부 발진?", "keywords": ["발진","두드러기","붉은","반점"]},
            {"id": "neck_stiff", "label": "경부강직", "question": "목이 뻣뻣?", "keywords": ["목","뻣뻣","경직","숙이"]},
            {"id": "altered_mental", "label": "의식변화", "question": "의식이 흐리나요?", "keywords": ["의식","멍","헛소리","혼미"]}
        ],
        "context_questions": [
            {"id": "immune", "label": "면역상태", "keywords": ["면역","항암","스테로이드","이식"]},
            {"id": "travel", "label": "여행력", "keywords": ["여행","해외","출장"]},
            {"id": "age", "label": "연령", "keywords": ["아이","노인","영아","신생아"]}
        ]
    }
]

# ── 스키마 (SQLite) ──
SCHEMA_SQLITE = """
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
    consultation_eval_json TEXT,
    token_usage_json TEXT,
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
    selected_text TEXT DEFAULT '',
    user_query TEXT DEFAULT '',
    full_response TEXT DEFAULT '',
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
    results_json TEXT,
    status TEXT DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    session_type TEXT NOT NULL,
    user_id TEXT DEFAULT '',
    user_name TEXT DEFAULT '',
    user_uid TEXT DEFAULT '',
    data_json TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_env ON conversations(env);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_comments_msg ON comments(message_id);
CREATE INDEX IF NOT EXISTS idx_comments_conv ON comments(conversation_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_category ON scenarios(category);
CREATE INDEX IF NOT EXISTS idx_test_runs_date ON test_runs(run_at);

CREATE TABLE IF NOT EXISTS consultation_checklists (
    symptom_key TEXT PRIMARY KEY,
    symptom_name TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    required_questions_json TEXT NOT NULL,
    red_flags_json TEXT,
    context_questions_json TEXT,
    guidance_criteria_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_enhancements (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    original_msg_id TEXT,
    enhanced_msg_id TEXT,
    original_query TEXT NOT NULL,
    enhanced_prompt TEXT NOT NULL,
    instructions_json TEXT,
    original_eval_json TEXT,
    enhanced_eval_json TEXT,
    improvement_json TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS response_feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    evaluator_id TEXT NOT NULL,
    evaluator_name TEXT DEFAULT '',
    rating INTEGER,
    legal_rating INTEGER,
    quality_rating INTEGER,
    labels_json TEXT DEFAULT '[]',
    corrected_response TEXT DEFAULT '',
    feedback_note TEXT DEFAULT '',
    original_query TEXT DEFAULT '',
    full_response TEXT DEFAULT '',
    response_time_ms INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS preference_pairs (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    response_chosen TEXT NOT NULL,
    response_rejected TEXT NOT NULL,
    chosen_legal_score REAL,
    rejected_legal_score REAL,
    chosen_consult_score REAL,
    rejected_consult_score REAL,
    chosen_composite REAL,
    rejected_composite REAL,
    label_source TEXT DEFAULT 'human',
    labeled_by TEXT DEFAULT '',
    label_confidence REAL DEFAULT 1.0,
    chosen_msg_id TEXT,
    rejected_msg_id TEXT,
    conversation_id TEXT,
    exported INTEGER DEFAULT 0,
    exported_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_msg ON response_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_conv ON response_feedback(conversation_id);
CREATE INDEX IF NOT EXISTS idx_feedback_evaluator ON response_feedback(evaluator_id);
CREATE INDEX IF NOT EXISTS idx_pref_pairs_source ON preference_pairs(label_source);
CREATE INDEX IF NOT EXISTS idx_pref_pairs_exported ON preference_pairs(exported);
"""

# ── 스키마 (PostgreSQL) ──
SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(char_length(name) <= 30),
    org TEXT DEFAULT '' CHECK(char_length(org) <= 100),
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
    title TEXT DEFAULT '' CHECK(char_length(title) <= 100),
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
    compliance_json JSONB,
    search_results_json JSONB,
    follow_ups_json JSONB,
    gpt_eval_json JSONB,
    gpt_model TEXT,
    consultation_eval_json JSONB,
    token_usage_json JSONB,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL CHECK(char_length(content) <= 2000),
    selected_text TEXT DEFAULT '',
    user_query TEXT DEFAULT '',
    full_response TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    prompt TEXT NOT NULL CHECK(char_length(prompt) <= 5000),
    expected_behavior TEXT DEFAULT '',
    should_refuse INTEGER DEFAULT 0,
    risk_level TEXT DEFAULT 'MEDIUM',
    tags_json JSONB DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    source TEXT DEFAULT 'manual',
    parent_id TEXT,
    generation_info_json JSONB,
    source_conversation_id TEXT,
    follow_ups_json JSONB DEFAULT '[]',
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
    results_json JSONB,
    status TEXT DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    session_type TEXT NOT NULL,
    user_id TEXT DEFAULT '',
    user_name TEXT DEFAULT '',
    user_uid TEXT DEFAULT '',
    data_json TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_env ON conversations(env);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_comments_msg ON comments(message_id);
CREATE INDEX IF NOT EXISTS idx_comments_conv ON comments(conversation_id);
CREATE INDEX IF NOT EXISTS idx_scenarios_category ON scenarios(category);
CREATE INDEX IF NOT EXISTS idx_test_runs_date ON test_runs(run_at);

CREATE TABLE IF NOT EXISTS consultation_checklists (
    symptom_key TEXT PRIMARY KEY,
    symptom_name TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    required_questions_json JSONB NOT NULL,
    red_flags_json JSONB,
    context_questions_json JSONB,
    guidance_criteria_json JSONB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_enhancements (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    original_msg_id TEXT,
    enhanced_msg_id TEXT,
    original_query TEXT NOT NULL,
    enhanced_prompt TEXT NOT NULL,
    instructions_json JSONB,
    original_eval_json JSONB,
    enhanced_eval_json JSONB,
    improvement_json JSONB,
    created_at TEXT NOT NULL,
    created_by TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS response_feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    evaluator_id TEXT NOT NULL,
    evaluator_name TEXT DEFAULT '',
    rating INTEGER,
    legal_rating INTEGER,
    quality_rating INTEGER,
    labels_json JSONB DEFAULT '[]',
    corrected_response TEXT DEFAULT '',
    feedback_note TEXT DEFAULT '',
    original_query TEXT DEFAULT '',
    full_response TEXT DEFAULT '',
    response_time_ms INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS preference_pairs (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    response_chosen TEXT NOT NULL,
    response_rejected TEXT NOT NULL,
    chosen_legal_score REAL,
    rejected_legal_score REAL,
    chosen_consult_score REAL,
    rejected_consult_score REAL,
    chosen_composite REAL,
    rejected_composite REAL,
    label_source TEXT DEFAULT 'human',
    labeled_by TEXT DEFAULT '',
    label_confidence REAL DEFAULT 1.0,
    chosen_msg_id TEXT,
    rejected_msg_id TEXT,
    conversation_id TEXT,
    exported INTEGER DEFAULT 0,
    exported_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_msg ON response_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_conv ON response_feedback(conversation_id);
CREATE INDEX IF NOT EXISTS idx_feedback_evaluator ON response_feedback(evaluator_id);
CREATE INDEX IF NOT EXISTS idx_pref_pairs_source ON preference_pairs(label_source);
CREATE INDEX IF NOT EXISTS idx_pref_pairs_exported ON preference_pairs(exported);
"""

# Keep backward compat alias
SCHEMA = SCHEMA_SQLITE


# ════════════════════════════════════════
#  SQL 헬퍼 (SQLite vs PostgreSQL 차이 흡수)
# ════════════════════════════════════════

def _ph(*args):
    """Placeholder: ? (SQLite) vs %s (PostgreSQL). _ph(n) returns n comma-separated placeholders."""
    n = args[0] if args else 1
    return ','.join(['%s'] * n) if _use_postgres else ','.join(['?'] * n)


def _p(n=1):
    """Single placeholder string."""
    return '%s' if _use_postgres else '?'


def _upsert(table, key_col, key_val, columns, values):
    """INSERT ... ON CONFLICT UPDATE helper. Returns (sql, params)."""
    ph = _p()
    col_list = ', '.join(columns)
    ph_list = ', '.join([ph] * len(columns))
    if _use_postgres:
        update_parts = ', '.join(f"{c} = EXCLUDED.{c}" for c in columns if c != key_col)
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({ph_list}) ON CONFLICT ({key_col}) DO UPDATE SET {update_parts}"
    else:
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({ph_list})"
    return sql, values


def _row_to_dict(row):
    """sqlite3.Row 또는 RealDictCursor dict -> dict 변환"""
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)  # RealDictCursor already returns dict-like
    return dict(row)


def _pg_json_loads(val):
    """PostgreSQL JSONB returns Python objects directly; SQLite stores as TEXT strings."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val  # already parsed by psycopg2
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _pg_json_loads_or(val, default):
    """Like _pg_json_loads but with a default."""
    result = _pg_json_loads(val)
    return result if result is not None else default


# ════════════════════════════════════════
#  DB 초기화 + 커넥션 관리
# ════════════════════════════════════════

def init_db(db_path=None):
    """데이터베이스 초기화 (스키마 생성)"""
    global _pg_pool, _use_postgres

    if DATABASE_URL and HAS_POSTGRES:
        # ── PostgreSQL 모드 ──
        _use_postgres = True
        if _pg_pool is None:
            _pg_pool = pg_pool.SimpleConnectionPool(1, 10, DATABASE_URL)

        conn = _pg_pool.getconn()
        try:
            conn.autocommit = True
            cur = conn.cursor()
            # PostgreSQL: executescript 없으므로 개별 실행
            # 세미콜론으로 분리하여 실행
            for statement in SCHEMA_PG.split(';'):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
            # 마이그레이션
            migrations_pg = [
                "ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'completed'",
                "ALTER TABLE comments ADD COLUMN IF NOT EXISTS selected_text TEXT DEFAULT ''",
                "ALTER TABLE comments ADD COLUMN IF NOT EXISTS user_query TEXT DEFAULT ''",
                "ALTER TABLE comments ADD COLUMN IF NOT EXISTS full_response TEXT DEFAULT ''",
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS consultation_eval_json JSONB",
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS token_usage_json JSONB",
            ]
            for sql in migrations_pg:
                try:
                    cur.execute(sql)
                except Exception:
                    pass
            # prompt_enhancements 테이블 마이그레이션
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS prompt_enhancements (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    original_msg_id TEXT,
                    enhanced_msg_id TEXT,
                    original_query TEXT NOT NULL,
                    enhanced_prompt TEXT NOT NULL,
                    instructions_json JSONB,
                    original_eval_json JSONB,
                    enhanced_eval_json JSONB,
                    improvement_json JSONB,
                    created_at TEXT NOT NULL,
                    created_by TEXT DEFAULT ''
                )""")
            except Exception:
                pass
            # RLHF 테이블 마이그레이션
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS response_feedback (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    evaluator_id TEXT NOT NULL,
                    evaluator_name TEXT DEFAULT '',
                    rating INTEGER,
                    legal_rating INTEGER,
                    quality_rating INTEGER,
                    labels_json JSONB DEFAULT '[]',
                    corrected_response TEXT DEFAULT '',
                    feedback_note TEXT DEFAULT '',
                    original_query TEXT DEFAULT '',
                    full_response TEXT DEFAULT '',
                    response_time_ms INTEGER,
                    created_at TEXT NOT NULL
                )""")
            except Exception:
                pass
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS preference_pairs (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    response_chosen TEXT NOT NULL,
                    response_rejected TEXT NOT NULL,
                    chosen_legal_score REAL,
                    rejected_legal_score REAL,
                    chosen_consult_score REAL,
                    rejected_consult_score REAL,
                    chosen_composite REAL,
                    rejected_composite REAL,
                    label_source TEXT DEFAULT 'human',
                    labeled_by TEXT DEFAULT '',
                    label_confidence REAL DEFAULT 1.0,
                    chosen_msg_id TEXT,
                    rejected_msg_id TEXT,
                    conversation_id TEXT,
                    exported INTEGER DEFAULT 0,
                    exported_at TEXT,
                    created_at TEXT NOT NULL
                )""")
            except Exception:
                pass
            # 고아 running 배치 정리
            try:
                cur.execute("UPDATE test_runs SET status = 'cancelled' WHERE status = 'running'")
            except Exception:
                pass
            cur.close()
        finally:
            _pg_pool.putconn(conn)
    else:
        # ── SQLite 모드 ──
        _use_postgres = False
        path = db_path or DB_PATH
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.executescript(SCHEMA_SQLITE)
        # 마이그레이션
        migrations = [
            "ALTER TABLE test_runs ADD COLUMN status TEXT DEFAULT 'completed'",
            "ALTER TABLE comments ADD COLUMN selected_text TEXT DEFAULT ''",
            "ALTER TABLE comments ADD COLUMN user_query TEXT DEFAULT ''",
            "ALTER TABLE comments ADD COLUMN full_response TEXT DEFAULT ''",
            "ALTER TABLE messages ADD COLUMN consultation_eval_json TEXT",
            "ALTER TABLE messages ADD COLUMN token_usage_json TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        # prompt_enhancements 테이블 마이그레이션
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS prompt_enhancements (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                original_msg_id TEXT,
                enhanced_msg_id TEXT,
                original_query TEXT NOT NULL,
                enhanced_prompt TEXT NOT NULL,
                instructions_json TEXT,
                original_eval_json TEXT,
                enhanced_eval_json TEXT,
                improvement_json TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT DEFAULT ''
            )""")
        except sqlite3.OperationalError:
            pass
        # 고아 running 배치 정리
        try:
            conn.execute("UPDATE test_runs SET status = 'cancelled' WHERE status = 'running'")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    # 기본 체크리스트 초기화
    try:
        init_checklists()
    except Exception:
        pass

    return DATABASE_URL if _use_postgres else (db_path or DB_PATH)


@contextmanager
def get_conn(db_path=None):
    """듀얼 모드 커넥션 컨텍스트 매니저. yields (conn, cur)."""
    if _use_postgres:
        conn = _pg_pool.getconn()
        try:
            conn.autocommit = False
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            _pg_pool.putconn(conn)
    else:
        path = db_path or DB_PATH
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        cursor = conn.cursor()
        try:
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════
#  사용자 (Users)
# ════════════════════════════════════════

def get_user(user_id):
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM users WHERE id = {_p()}", (user_id,))
        row = cur.fetchone()
        return _row_to_dict(row)


def create_user(data):
    name = data.get('name', '')[:MAX_NAME_LENGTH]
    org = data.get('org', '')[:MAX_ORG_LENGTH]
    now = _now()
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(
            f"INSERT INTO users (id, name, org, password_hash, password_salt, status, role, uid, created_at) VALUES ({_ph(9)})",
            (data['id'], name, org, data['password_hash'], data['password_salt'],
             data.get('status', 'pending'), data.get('role', 'tester'), data.get('uid', ''), now)
        )
    return get_user(data['id'])


def update_user(user_id, updates):
    allowed = ['name', 'org', 'password_hash', 'password_salt', 'status', 'role', 'uid', 'approved_at', 'approved_by']
    sets = []
    vals = []
    ph = _p()
    for k, v in updates.items():
        if k in allowed:
            sets.append(f"{k} = {ph}")
            vals.append(v)
    if not sets:
        return False
    vals.append(user_id)
    with get_conn() as (conn, cur):
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = {ph}", vals)
    return True


def get_pending_users():
    with get_conn() as (conn, cur):
        cur.execute("SELECT * FROM users WHERE status = 'pending' ORDER BY created_at")
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_all_users():
    with get_conn() as (conn, cur):
        cur.execute("SELECT * FROM users ORDER BY created_at")
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_users_by_status(status):
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM users WHERE status = {_p()} ORDER BY created_at", (status,))
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def delete_user(user_id):
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM users WHERE id = {_p()}", (user_id,))
    return True


# ════════════════════════════════════════
#  대화 (Conversations)
# ════════════════════════════════════════

def get_conversations(user_id=None, limit=50, offset=0):
    ph = _p()
    with get_conn() as (conn, cur):
        if user_id:
            cur.execute(
                f"""SELECT c.*, COUNT(m.id) as message_count
                   FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.user_id = {ph}
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT {ph} OFFSET {ph}""",
                (user_id, limit, offset)
            )
        else:
            cur.execute(
                f"""SELECT c.*, COUNT(m.id) as message_count
                   FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT {ph} OFFSET {ph}""",
                (limit, offset)
            )
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_conversation(conv_id):
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM conversations WHERE id = {ph}", (conv_id,))
        conv = cur.fetchone()
        if not conv:
            return None
        result = _row_to_dict(conv)

        # 메시지 로드
        cur.execute(
            f"SELECT * FROM messages WHERE conversation_id = {ph} ORDER BY timestamp", (conv_id,)
        )
        msg_rows = cur.fetchall()
        messages = []
        for mr in msg_rows:
            msg = _row_to_dict(mr)
            # JSON 필드 파싱 (snake_case -> camelCase)
            json_field_map = {
                'compliance_json': 'compliance',
                'search_results_json': 'searchResults',
                'follow_ups_json': 'followUps',
                'gpt_eval_json': 'gptEval',
                'consultation_eval_json': 'consultationEval',
                'token_usage_json': 'tokenUsage',
            }
            for jf, key in json_field_map.items():
                raw = msg.pop(jf, None)
                if raw:
                    msg[key] = _pg_json_loads(raw)
                else:
                    msg[key] = None
            # 커멘트 로드
            cur.execute(
                f"SELECT * FROM comments WHERE message_id = {ph} ORDER BY created_at", (msg['id'],)
            )
            cmt_rows = cur.fetchall()
            msg['comments'] = [_row_to_dict(c) for c in cmt_rows]
            # 필드명 정리 (snake_case -> camelCase)
            msg['msgId'] = msg.pop('id')
            msg.pop('conversation_id', None)
            if 'response_time' in msg:
                msg['responseTime'] = msg.pop('response_time')
            if 'gpt_model' in msg:
                msg['gptModel'] = msg.pop('gpt_model')
            messages.append(msg)

        result['messages'] = messages
        # 필드명 호환 (snake -> camel)
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
    with get_conn() as (conn, cur):
        cur.execute(
            f"INSERT INTO conversations (id, user_id, user_name, title, env, conversation_strid, created_at, updated_at) VALUES ({_ph(8)})",
            (conv_id, data.get('userId', ''), data.get('userName', ''), title,
             data.get('env', 'dev'), data.get('conversationStrid', ''), now, now)
        )
    return get_conversation(conv_id)


def add_message(conv_id, msg_data):
    msg_id = msg_data.get('msgId') or f"msg-{secrets.token_hex(4)}"
    now = _now()
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(
            f"""INSERT INTO messages (id, conversation_id, role, content, timestamp, response_time,
               compliance_json, search_results_json, follow_ups_json, gpt_eval_json, gpt_model, token_usage_json)
               VALUES ({_ph(12)})""",
            (msg_id, conv_id, msg_data.get('role', 'user'), msg_data.get('content', ''),
             msg_data.get('timestamp', now), msg_data.get('responseTime'),
             json.dumps(msg_data.get('compliance'), ensure_ascii=False) if msg_data.get('compliance') else None,
             json.dumps(msg_data.get('searchResults'), ensure_ascii=False) if msg_data.get('searchResults') else None,
             json.dumps(msg_data.get('followUps'), ensure_ascii=False) if msg_data.get('followUps') else None,
             json.dumps(msg_data.get('gptEval'), ensure_ascii=False) if msg_data.get('gptEval') else None,
             msg_data.get('gptModel'),
             json.dumps(msg_data.get('tokenUsage'), ensure_ascii=False) if msg_data.get('tokenUsage') else None)
        )
        cur.execute(f"UPDATE conversations SET updated_at = {ph} WHERE id = {ph}", (now, conv_id))
    return msg_id


def update_message(conv_id, msg_id, updates):
    """메시지 필드 업데이트 (gptEval, compliance 등)"""
    allowed_json = {'compliance': 'compliance_json', 'searchResults': 'search_results_json',
                    'followUps': 'follow_ups_json', 'gptEval': 'gpt_eval_json',
                    'consultationEval': 'consultation_eval_json',
                    'tokenUsage': 'token_usage_json'}
    allowed_plain = {'gptModel': 'gpt_model', 'responseTime': 'response_time'}
    ph = _p()
    sets = []
    vals = []
    for k, v in updates.items():
        if k in allowed_json:
            sets.append(f"{allowed_json[k]} = {ph}")
            vals.append(json.dumps(v, ensure_ascii=False) if v else None)
        elif k in allowed_plain:
            sets.append(f"{allowed_plain[k]} = {ph}")
            vals.append(v)
    if not sets:
        return False
    vals.extend([msg_id, conv_id])
    with get_conn() as (conn, cur):
        cur.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id = {ph} AND conversation_id = {ph}", vals)
        rowcount = cur.rowcount
        if rowcount == 0:
            return False
        cur.execute(f"UPDATE conversations SET updated_at = {ph} WHERE id = {ph}", (_now(), conv_id))
    return True


def get_last_assistant_msg_id(conv_id):
    """대화의 마지막 assistant 메시지 ID 반환"""
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(
            f"SELECT id FROM messages WHERE conversation_id = {ph} AND role = 'assistant' ORDER BY timestamp DESC LIMIT 1",
            (conv_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        r = _row_to_dict(row)
        return r['id'] if r else None


def delete_conversation(conv_id):
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM conversations WHERE id = {_p()}", (conv_id,))
    return True


def search_conversations(user_id=None, query='', limit=50):
    ph = _p()
    with get_conn() as (conn, cur):
        if user_id:
            cur.execute(
                f"""SELECT DISTINCT c.*, COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.user_id = {ph} AND (c.title LIKE {ph} OR EXISTS (
                     SELECT 1 FROM messages m2 WHERE m2.conversation_id = c.id AND m2.content LIKE {ph}
                   ))
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT {ph}""",
                (user_id, f'%{query}%', f'%{query}%', limit)
            )
        else:
            cur.execute(
                f"""SELECT DISTINCT c.*, COUNT(m.id) as message_count
                   FROM conversations c
                   LEFT JOIN messages m ON c.id = m.conversation_id
                   WHERE c.title LIKE {ph} OR EXISTS (
                     SELECT 1 FROM messages m2 WHERE m2.conversation_id = c.id AND m2.content LIKE {ph}
                   )
                   GROUP BY c.id ORDER BY c.updated_at DESC LIMIT {ph}""",
                (f'%{query}%', f'%{query}%', limit)
            )
        rows = cur.fetchall()
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
    ph = _p()

    with get_conn() as (conn, cur):
        # msg_id 확인, 없으면 마지막 assistant 메시지에 fallback
        cur.execute(f"SELECT id FROM messages WHERE id = {ph} AND conversation_id = {ph}", (msg_id, conv_id))
        msg = cur.fetchone()
        if not msg:
            cur.execute(
                f"SELECT id FROM messages WHERE conversation_id = {ph} AND role = 'assistant' ORDER BY timestamp DESC LIMIT 1",
                (conv_id,)
            )
            msg = cur.fetchone()
        if not msg:
            raise ValueError("메시지를 찾을 수 없습니다")

        msg_dict = _row_to_dict(msg)
        actual_msg_id = msg_dict['id']
        cur.execute(
            f"INSERT INTO comments (id, message_id, conversation_id, user_id, user_name, category, content, selected_text, user_query, full_response, created_at) VALUES ({_ph(11)})",
            (comment_id, actual_msg_id, conv_id, data.get('userId', ''), data.get('userName', ''),
             data.get('category', '기타'), content,
             data.get('selectedText', ''), data.get('userQuery', ''), data.get('fullResponse', ''),
             now)
        )
    return {"commentId": comment_id, "msgId": actual_msg_id, "createdAt": now}


def delete_comment(comment_id):
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM comments WHERE id = {_p()}", (comment_id,))
    return True


def export_comments(user_id=None):
    ph = _p()
    with get_conn() as (conn, cur):
        if user_id:
            cur.execute(
                f"""SELECT c.*, co.title as conv_title, m.content as msg_content, m.role
                   FROM comments c
                   JOIN conversations co ON c.conversation_id = co.id
                   JOIN messages m ON c.message_id = m.id
                   WHERE c.user_id = {ph}
                   ORDER BY c.created_at""", (user_id,)
            )
        else:
            cur.execute(
                """SELECT c.*, co.title as conv_title, m.content as msg_content, m.role
                   FROM comments c
                   JOIN conversations co ON c.conversation_id = co.id
                   JOIN messages m ON c.message_id = m.id
                   ORDER BY c.created_at"""
            )
        rows = cur.fetchall()

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
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute("SELECT * FROM scenarios ORDER BY id")
        rows = cur.fetchall()
        scenarios = []
        for r in rows:
            s = _row_to_dict(r)
            # JSON 필드 파싱 + 필드명 변환
            s['shouldRefuse'] = bool(s.pop('should_refuse', 0))
            s['riskLevel'] = s.pop('risk_level', 'MEDIUM')
            s['expectedBehavior'] = s.pop('expected_behavior', '')
            s['tags'] = _pg_json_loads_or(s.pop('tags_json', '[]'), [])
            s['enabled'] = bool(s.pop('enabled', 1))
            s['parentId'] = s.pop('parent_id', None)
            s['generationInfo'] = _pg_json_loads(s.pop('generation_info_json', None))
            s['sourceConversationId'] = s.pop('source_conversation_id', None)
            s['followUps'] = _pg_json_loads_or(s.pop('follow_ups_json', '[]'), [])
            s['createdAt'] = s.pop('created_at', '')
            s['updatedAt'] = s.pop('updated_at', '')
            scenarios.append(s)

        # 카테고리 (settings 테이블 또는 기본값)
        cur.execute(f"SELECT value FROM settings WHERE key = {ph}", ('categories',))
        cat_row = cur.fetchone()
        if cat_row:
            cat_dict = _row_to_dict(cat_row)
            categories = _pg_json_loads_or(cat_dict['value'], DEFAULT_CATEGORIES)
        else:
            categories = DEFAULT_CATEGORIES

    return {
        "version": "1.0",
        "lastModified": _now(),
        "categories": categories,
        "scenarios": scenarios
    }


def get_scenario(scenario_id):
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM scenarios WHERE id = {ph}", (scenario_id,))
        row = cur.fetchone()
        if not row:
            return None
        s = _row_to_dict(row)
        s['shouldRefuse'] = bool(s.pop('should_refuse', 0))
        s['riskLevel'] = s.pop('risk_level', 'MEDIUM')
        s['expectedBehavior'] = s.pop('expected_behavior', '')
        s['tags'] = _pg_json_loads_or(s.pop('tags_json', '[]'), [])
        s['enabled'] = bool(s.pop('enabled', 1))
        s['parentId'] = s.pop('parent_id', None)
        s['generationInfo'] = _pg_json_loads(s.pop('generation_info_json', None))
        s['sourceConversationId'] = s.pop('source_conversation_id', None)
        s['followUps'] = _pg_json_loads_or(s.pop('follow_ups_json', '[]'), [])
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
    ph = _p()

    with get_conn() as (conn, cur):
        # 중복 체크
        cur.execute(f"SELECT id FROM scenarios WHERE id = {ph}", (scenario_id,))
        existing = cur.fetchone()
        if existing:
            raise ValueError(f"이미 존재하는 ID: {scenario_id}")

        cur.execute(
            f"""INSERT INTO scenarios (id, category, subcategory, prompt, expected_behavior, should_refuse,
               risk_level, tags_json, enabled, source, parent_id, generation_info_json,
               source_conversation_id, follow_ups_json, created_at, updated_at)
               VALUES ({_ph(16)})""",
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
    ph = _p()
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

    sets = [f"{k} = {ph}" for k in updates.keys()]
    vals = list(updates.values()) + [scenario_id]

    with get_conn() as (conn, cur):
        cur.execute(f"UPDATE scenarios SET {', '.join(sets)} WHERE id = {ph}", vals)
    return get_scenario(scenario_id)


def delete_scenario(scenario_id):
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM scenarios WHERE id = {_p()}", (scenario_id,))
    return True


def delete_scenarios_bulk(scenario_ids):
    placeholders = _ph(len(scenario_ids))
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM scenarios WHERE id IN ({placeholders})", scenario_ids)
    return True


def get_categories():
    """카테고리 목록 반환 (DB 저장값 또는 기본값)"""
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT value FROM settings WHERE key = {ph}", ('categories',))
        cat_row = cur.fetchone()
        if cat_row:
            cat_dict = _row_to_dict(cat_row)
            return _pg_json_loads_or(cat_dict['value'], list(DEFAULT_CATEGORIES))
    return list(DEFAULT_CATEGORIES)


def _generate_scenario_id(category_id):
    categories = get_categories()
    prefix = None
    for cat in categories:
        if cat['id'] == category_id:
            prefix = cat.get('prefix')
            break
    if not prefix:
        prefix = category_id[:4].upper()
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT id FROM scenarios WHERE id LIKE {ph}", (f"{prefix}-%",))
        rows = cur.fetchall()
        nums = []
        for r in rows:
            rd = _row_to_dict(r)
            parts = rd['id'].split('-')
            if len(parts) >= 2 and parts[-1].isdigit():
                nums.append(int(parts[-1]))
        next_num = max(nums, default=0) + 1
    return f"{prefix}-{next_num:03d}"


def save_scenario_categories(categories):
    with get_conn() as (conn, cur):
        now = _now()
        sql, params = _upsert('settings', 'key', 'categories',
                              ['key', 'value', 'updated_at'],
                              ('categories', json.dumps(categories, ensure_ascii=False), now))
        cur.execute(sql, params)


# ════════════════════════════════════════
#  테스트 이력 (Test Runs)
# ════════════════════════════════════════

def get_test_runs(limit=50):
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM test_runs ORDER BY run_at DESC LIMIT {ph}", (limit,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = _row_to_dict(r)
            d['runAt'] = d.pop('run_at', '')
            d['guidelineVersion'] = d.pop('guideline_version', '')
            d['results'] = _pg_json_loads_or(d.pop('results_json', '[]'), [])
            result.append(d)
        return result


def get_test_run(run_id):
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM test_runs WHERE id = {ph}", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        d['runAt'] = d.pop('run_at', '')
        d['guidelineVersion'] = d.pop('guideline_version', '')
        d['results'] = _pg_json_loads_or(d.pop('results_json', '[]'), [])
        return d


def save_test_run(data):
    run_id = data.get('id') or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    now = _now()
    status = data.get('status', 'completed')
    with get_conn() as (conn, cur):
        sql, params = _upsert(
            'test_runs', 'id', run_id,
            ['id', 'run_at', 'total', 'passed', 'failed', 'env', 'guideline_version', 'tester', 'results_json', 'status'],
            (run_id, data.get('runAt', now), data.get('total', 0), data.get('passed', 0),
             data.get('failed', 0), data.get('env', 'dev'), data.get('guidelineVersion', ''),
             data.get('tester', ''),
             json.dumps(data.get('results', []), ensure_ascii=False),
             status)
        )
        cur.execute(sql, params)
    return run_id


# ════════════════════════════════════════
#  문진 체크리스트 (Consultation Checklists)
# ════════════════════════════════════════

def init_checklists():
    """기본 체크리스트 초기화 (이미 존재하면 건너뜀)"""
    now = _now()
    ph = _p()
    with get_conn() as (conn, cur):
        for cl in DEFAULT_CHECKLISTS:
            cur.execute(f"SELECT symptom_key FROM consultation_checklists WHERE symptom_key = {ph}",
                        (cl['symptom_key'],))
            existing = cur.fetchone()
            if not existing:
                guidance = {
                    'department': cl.get('department', ''),
                    'detail': cl.get('detail', ''),
                    'ageSpecific': cl.get('age_specific', {}),
                }
                cur.execute(
                    f"""INSERT INTO consultation_checklists
                       (symptom_key, symptom_name, category, required_questions_json, red_flags_json,
                        context_questions_json, guidance_criteria_json, created_at, updated_at)
                       VALUES ({_ph(9)})""",
                    (cl['symptom_key'], cl['symptom_name'], cl.get('category', 'general'),
                     json.dumps(cl.get('required_questions', []), ensure_ascii=False),
                     json.dumps(cl.get('red_flags', []), ensure_ascii=False),
                     json.dumps(cl.get('context_questions', []), ensure_ascii=False),
                     json.dumps(guidance, ensure_ascii=False),
                     now, now)
                )


def get_checklists():
    """전체 체크리스트 조회"""
    with get_conn() as (conn, cur):
        cur.execute("SELECT * FROM consultation_checklists ORDER BY symptom_name")
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = _row_to_dict(r)
            for jf in ['required_questions_json', 'red_flags_json', 'context_questions_json', 'guidance_criteria_json']:
                key = jf.replace('_json', '').replace('_', '')
                camel = jf.replace('_json', '')
                # snake_case -> camelCase
                parts = camel.split('_')
                camel_key = parts[0] + ''.join(p.capitalize() for p in parts[1:])
                raw = d.pop(jf, None)
                d[camel_key] = _pg_json_loads_or(raw, [])
            d['symptomKey'] = d.pop('symptom_key', '')
            d['symptomName'] = d.pop('symptom_name', '')
            d['createdAt'] = d.pop('created_at', '')
            d['updatedAt'] = d.pop('updated_at', '')
            result.append(d)
        return result


def get_checklist(symptom_key):
    """단일 체크리스트 조회"""
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM consultation_checklists WHERE symptom_key = {ph}",
                    (symptom_key,))
        row = cur.fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        for jf in ['required_questions_json', 'red_flags_json', 'context_questions_json', 'guidance_criteria_json']:
            parts = jf.replace('_json', '').split('_')
            camel_key = parts[0] + ''.join(p.capitalize() for p in parts[1:])
            raw = d.pop(jf, None)
            d[camel_key] = _pg_json_loads_or(raw, [])
        d['symptomKey'] = d.pop('symptom_key', '')
        d['symptomName'] = d.pop('symptom_name', '')
        d['createdAt'] = d.pop('created_at', '')
        d['updatedAt'] = d.pop('updated_at', '')
        return d


def save_checklist(data):
    """체크리스트 저장 (생성 또는 업데이트)"""
    now = _now()
    ph = _p()
    key = data.get('symptomKey', '')
    if not key:
        raise ValueError("symptomKey 필수")
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT symptom_key FROM consultation_checklists WHERE symptom_key = {ph}",
                    (key,))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                f"""UPDATE consultation_checklists SET
                   symptom_name={ph}, category={ph}, required_questions_json={ph}, red_flags_json={ph},
                   context_questions_json={ph}, guidance_criteria_json={ph}, updated_at={ph}
                   WHERE symptom_key={ph}""",
                (data.get('symptomName', ''), data.get('category', 'general'),
                 json.dumps(data.get('requiredQuestions', []), ensure_ascii=False),
                 json.dumps(data.get('redFlags', []), ensure_ascii=False),
                 json.dumps(data.get('contextQuestions', []), ensure_ascii=False),
                 json.dumps(data.get('guidanceCriteria', []), ensure_ascii=False),
                 now, key)
            )
        else:
            cur.execute(
                f"""INSERT INTO consultation_checklists
                   (symptom_key, symptom_name, category, required_questions_json, red_flags_json,
                    context_questions_json, guidance_criteria_json, created_at, updated_at)
                   VALUES ({_ph(9)})""",
                (key, data.get('symptomName', ''), data.get('category', 'general'),
                 json.dumps(data.get('requiredQuestions', []), ensure_ascii=False),
                 json.dumps(data.get('redFlags', []), ensure_ascii=False),
                 json.dumps(data.get('contextQuestions', []), ensure_ascii=False),
                 json.dumps(data.get('guidanceCriteria', []), ensure_ascii=False),
                 now, now)
            )
    return get_checklist(key)


def delete_checklist(symptom_key):
    """체크리스트 삭제"""
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM consultation_checklists WHERE symptom_key = {_p()}", (symptom_key,))
    return True


def match_checklists(query_text):
    """사용자 질문에서 증상 키워드 매칭하여 관련 체크리스트 반환"""
    # 증상 유의어 매핑 (사용자 표현 -> 체크리스트 키워드)
    SYMPTOM_ALIASES = {
        'headache': ['머리','두통','편두통','머리아','머리가','뒷머리','앞머리','관자놀이','두개'],
        'abdominal_pain': ['배','복통','배아','배가','속','아랫배','윗배','명치','옆구리'],
        'chest_pain': ['가슴','흉통','가슴아','가슴이','쥐어짜','답답'],
        'chest_pain_resp': ['가슴','흉통','숨쉴때','가슴통'],
        'cough': ['기침','콜록','가래','객담'],
        'fatigue': ['피곤','피로','무기력','지침','기운','힘이 없','지쳤'],
        'fever': ['열','발열','고열','미열','오한','38도','39도','40도','체온'],
        'dizziness': ['어지러','어지럼','빙빙','현기증','핑','눈앞'],
        'back_pain': ['허리','요통','디스크','척추','허리아','허리가'],
        'knee_pain': ['무릎','관절','무릎아','무릎이'],
        'shoulder_pain': ['어깨','오십견','어깨아','어깨가','팔이'],
        'heartburn': ['속쓰림','역류','쓰린','속이','소화','체한','더부룩'],
        'diarrhea': ['설사','묽은','물변'],
        'constipation': ['변비','배변','못봐','안나'],
        'bloody_stool': ['혈변','피','검은변','선혈'],
        'dyspnea': ['숨','호흡','답답','헐떡','가빠','숨차'],
        'palpitation': ['두근','심장','빨리뛰','심계'],
        'insomnia': ['잠','불면','수면','못자','뒤척','깬다'],
        'anxiety': ['불안','긴장','공황','초조','걱정'],
        'depression': ['우울','무기력','슬프','의욕','흥미'],
        'stress': ['스트레스','번아웃','지침','힘들'],
        'rash': ['발진','두드러기','빨간','반점','좁쌀'],
        'itching': ['가려','소양','긁','간지'],
        'numbness': ['저림','저린','마비','감각','찌릿'],
        'weight_change': ['체중','살이','빠지','쪘'],
        'body_pain': ['몸살','근육통','온몸','전신'],
        'dysuria': ['소변','배뇨','오줌','찌릿'],
        'frequency': ['소변','자주','빈뇨','화장실'],
        'hematuria': ['혈뇨','피','소변에'],
        'menstrual': ['생리','월경','불규칙'],
        'vision_loss': ['시력','안보','흐릿','눈','시야'],
        'eye_pain': ['눈','충혈','이물감','눈아'],
        'ear_pain': ['귀','이명','귀아','중이염'],
        'nasal_congestion': ['코','코막','비염','축농'],
        'throat_pain': ['목','인후','목아','쉰','삼킴'],
        'seizure': ['경련','발작','의식','쓰러'],
        'memory_loss': ['기억','깜빡','집중','건망'],
        'myalgia': ['근육','근육통','뭉침','담','결림'],
        'leg_edema': ['부종','붓','부은','발목'],
        'bp_abnormal': ['혈압','고혈압','저혈압','어지러'],
        'acne': ['여드름','뾰루지','피부'],
        'skin_tumor': ['점','혹','피부','종양','사마귀'],
    }

    checklists = get_checklists()
    matched = []
    text_lower = query_text.lower()
    for cl in checklists:
        name = cl.get('symptomName', '')
        key = cl.get('symptomKey', '')
        # 1. 증상명 직접 매칭
        if name in query_text:
            cl['_matchScore'] = 100
            matched.append(cl)
            continue
        # 2. 유의어 매칭
        aliases = SYMPTOM_ALIASES.get(key, [])
        alias_score = sum(2 for a in aliases if a in text_lower)
        if alias_score >= 2:
            cl['_matchScore'] = alias_score * 5
            matched.append(cl)
            continue
        # 3. 필수 질문의 키워드로 매칭
        score = 0
        for rq in cl.get('requiredQuestions', []):
            for kw in rq.get('keywords', []):
                if kw in text_lower:
                    score += 1
        for rf in cl.get('redFlags', []):
            for kw in rf.get('keywords', []):
                if kw in text_lower:
                    score += 2  # red flag 키워드 가중치
        if score >= 2:
            cl['_matchScore'] = score
            matched.append(cl)
    # 점수 높은 순
    matched.sort(key=lambda x: x.get('_matchScore', 0), reverse=True)
    return matched[:3]  # 최대 3개


# ════════════════════════════════════════
#  설정 (Settings)
# ════════════════════════════════════════

def get_settings():
    """모든 설정을 하나의 dict로 반환 (기존 settings.json 호환)"""
    with get_conn() as (conn, cur):
        cur.execute("SELECT key, value FROM settings")
        rows = cur.fetchall()
        result = {}
        for r in rows:
            rd = _row_to_dict(r)
            val = _pg_json_loads(rd['value'])
            if val is not None:
                result[rd['key']] = val
            else:
                result[rd['key']] = rd['value']
        return result


def save_settings(data):
    """dict를 개별 키-값으로 저장 (기존 settings.json 호환)"""
    now = _now()
    ph = _p()
    # 민감 데이터는 별도 처리 (users 테이블로 이동됨)
    skip_keys = {'adminPasswordHash', 'adminPasswordSalt', 'testerAccounts', 'users'}
    with get_conn() as (conn, cur):
        for k, v in data.items():
            if k in skip_keys:
                continue
            val_str = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            sql, params = _upsert('settings', 'key', k,
                                  ['key', 'value', 'updated_at'],
                                  (k, val_str, now))
            cur.execute(sql, params)


# ════════════════════════════════════════
#  세션 관리 (DB 기반 — 멀티 인스턴스 공유)
# ════════════════════════════════════════

def save_session(token, session_type, user_id='', user_name='', user_uid='', data=None, max_age=86400):
    """세션 저장 (생성 또는 갱신)"""
    now = _now()
    from datetime import datetime, timezone, timedelta
    expires = (datetime.now(timezone.utc) + timedelta(seconds=max_age)).isoformat()
    data_json = json.dumps(data, ensure_ascii=False) if data else None
    sql, params = _upsert('sessions', 'token', token,
                          ['token', 'session_type', 'user_id', 'user_name', 'user_uid', 'data_json', 'created_at', 'expires_at'],
                          (token, session_type, user_id, user_name, user_uid, data_json, now, expires))
    with get_conn() as (conn, cur):
        cur.execute(sql, params)


def get_session(token):
    """세션 조회 (만료 확인 포함)"""
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM sessions WHERE token = {ph}", (token,))
        row = cur.fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        # 만료 확인
        from datetime import datetime, timezone
        try:
            expires = datetime.fromisoformat(d['expires_at'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires:
                delete_session(token)
                return None
        except:
            pass
        # data_json 파싱
        if d.get('data_json'):
            try:
                d['data'] = json.loads(d['data_json']) if isinstance(d['data_json'], str) else d['data_json']
            except:
                d['data'] = {}
        else:
            d['data'] = {}
        return d


def delete_session(token):
    """세션 삭제"""
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM sessions WHERE token = {ph}", (token,))


def delete_sessions_by_user(user_id, session_type=None):
    """특정 사용자의 세션 삭제"""
    ph = _p()
    with get_conn() as (conn, cur):
        if session_type:
            cur.execute(f"DELETE FROM sessions WHERE user_id = {ph} AND session_type = {ph}", (user_id, session_type))
        else:
            cur.execute(f"DELETE FROM sessions WHERE user_id = {ph}", (user_id,))


def cleanup_expired_sessions():
    """만료된 세션 정리"""
    now = _now()
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM sessions WHERE expires_at < {ph}", (now,))


def get_setting(key, default=None):
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT value FROM settings WHERE key = {ph}", (key,))
        row = cur.fetchone()
        if not row:
            return default
        rd = _row_to_dict(row)
        val = _pg_json_loads(rd['value'])
        if val is not None:
            return val
        return rd['value']


def set_setting(key, value):
    now = _now()
    val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    with get_conn() as (conn, cur):
        sql, params = _upsert('settings', 'key', key,
                              ['key', 'value', 'updated_at'],
                              (key, val_str, now))
        cur.execute(sql, params)


# ════════════════════════════════════════
#  프롬프트 보강 (Prompt Enhancements)
# ════════════════════════════════════════

def save_prompt_enhancement(data):
    """Save or update a prompt enhancement record"""
    now = _now()
    enhancement_id = data.get('id', f"enh-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}")
    with get_conn() as (conn, cur):
        sql, params = _upsert(
            'prompt_enhancements', 'id', enhancement_id,
            ['id', 'conversation_id', 'original_msg_id', 'enhanced_msg_id',
             'original_query', 'enhanced_prompt', 'instructions_json',
             'original_eval_json', 'enhanced_eval_json', 'improvement_json',
             'created_at', 'created_by'],
            (enhancement_id,
             data.get('conversationId', ''),
             data.get('originalMsgId', ''),
             data.get('enhancedMsgId', ''),
             data.get('originalQuery', ''),
             data.get('enhancedPrompt', ''),
             json.dumps(data.get('instructions', []), ensure_ascii=False),
             json.dumps(data.get('originalEval', {}), ensure_ascii=False),
             json.dumps(data.get('enhancedEval', {}), ensure_ascii=False),
             json.dumps(data.get('improvement', {}), ensure_ascii=False),
             now,
             data.get('createdBy', ''))
        )
        cur.execute(sql, params)
    return enhancement_id


def get_prompt_enhancements(conversation_id=None, limit=50):
    """List prompt enhancements, optionally filtered by conversation"""
    ph = _p()
    with get_conn() as (conn, cur):
        if conversation_id:
            cur.execute(
                f"SELECT * FROM prompt_enhancements WHERE conversation_id = {ph} ORDER BY created_at DESC LIMIT {ph}",
                (conversation_id, limit))
        else:
            cur.execute(
                f"SELECT * FROM prompt_enhancements ORDER BY created_at DESC LIMIT {ph}",
                (limit,))
        rows = cur.fetchall()
        results = []
        for row in rows:
            d = _row_to_dict(row)
            d['instructions'] = _pg_json_loads_or(d.pop('instructions_json', None), [])
            d['originalEval'] = _pg_json_loads_or(d.pop('original_eval_json', None), {})
            d['enhancedEval'] = _pg_json_loads_or(d.pop('enhanced_eval_json', None), {})
            d['improvement'] = _pg_json_loads_or(d.pop('improvement_json', None), {})
            results.append(d)
        return results


def get_prompt_enhancement(enhancement_id):
    """Get single enhancement by ID"""
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(f"SELECT * FROM prompt_enhancements WHERE id = {ph}", (enhancement_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        d['instructions'] = _pg_json_loads_or(d.pop('instructions_json', None), [])
        d['originalEval'] = _pg_json_loads_or(d.pop('original_eval_json', None), {})
        d['enhancedEval'] = _pg_json_loads_or(d.pop('enhanced_eval_json', None), {})
        d['improvement'] = _pg_json_loads_or(d.pop('improvement_json', None), {})
        return d


def get_enhancement_report():
    """Aggregate report: average improvement scores, most common instructions"""
    with get_conn() as (conn, cur):
        cur.execute("SELECT improvement_json, instructions_json FROM prompt_enhancements ORDER BY created_at DESC")
        rows = cur.fetchall()

    total = len(rows)
    if total == 0:
        return {'total': 0, 'avgGptDelta': 0, 'avgConsultDelta': 0, 'topInstructions': []}

    gpt_deltas = []
    consult_deltas = []
    instruction_counts = {}

    for row in rows:
        d = _row_to_dict(row)
        imp = _pg_json_loads_or(d.get('improvement_json'), {})
        if isinstance(imp, dict):
            gd = imp.get('gptDelta')
            if gd is not None:
                gpt_deltas.append(gd)
            cd = imp.get('consultDelta')
            if cd is not None:
                consult_deltas.append(cd)

        insts = _pg_json_loads_or(d.get('instructions_json'), [])
        if isinstance(insts, list):
            for inst in insts:
                instruction_counts[inst] = instruction_counts.get(inst, 0) + 1

    avg_gpt = sum(gpt_deltas) / len(gpt_deltas) if gpt_deltas else 0
    avg_consult = sum(consult_deltas) / len(consult_deltas) if consult_deltas else 0

    top_instructions = sorted(instruction_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_instructions = [{'instruction': inst, 'count': cnt} for inst, cnt in top_instructions]

    return {
        'total': total,
        'avgGptDelta': round(avg_gpt, 2),
        'avgConsultDelta': round(avg_consult, 2),
        'topInstructions': top_instructions,
    }


# ─── response_feedback CRUD ───────────────────────────────────────

def add_response_feedback(message_id, conversation_id, evaluator_id,
                           evaluator_name='', rating=None,
                           legal_rating=None, quality_rating=None,
                           labels_json='[]', corrected_response='',
                           feedback_note='', original_query='',
                           full_response='', response_time_ms=None):
    """응답 피드백 저장"""
    fb_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as (conn, cur):
        cur.execute(
            f"""INSERT INTO response_feedback
                (id, message_id, conversation_id, evaluator_id, evaluator_name,
                 rating, legal_rating, quality_rating, labels_json,
                 corrected_response, feedback_note, original_query,
                 full_response, response_time_ms, created_at)
                VALUES ({_ph(15)})""",
            (fb_id, message_id, conversation_id, evaluator_id, evaluator_name,
             rating, legal_rating, quality_rating, labels_json,
             corrected_response, feedback_note, original_query,
             full_response, response_time_ms, now)
        )
    return fb_id


def get_response_feedback(message_id=None, conversation_id=None,
                          evaluator_id=None, limit=100):
    """피드백 조회 (message_id, conversation_id, evaluator_id 중 하나로 필터)"""
    ph = _p()
    with get_conn() as (conn, cur):
        if message_id:
            cur.execute(
                f"SELECT * FROM response_feedback WHERE message_id = {ph} ORDER BY created_at DESC LIMIT {ph}",
                (message_id, limit)
            )
        elif conversation_id:
            cur.execute(
                f"SELECT * FROM response_feedback WHERE conversation_id = {ph} ORDER BY created_at DESC LIMIT {ph}",
                (conversation_id, limit)
            )
        elif evaluator_id:
            cur.execute(
                f"SELECT * FROM response_feedback WHERE evaluator_id = {ph} ORDER BY created_at DESC LIMIT {ph}",
                (evaluator_id, limit)
            )
        else:
            cur.execute(
                f"SELECT * FROM response_feedback ORDER BY created_at DESC LIMIT {ph}",
                (limit,)
            )
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_feedback_stats(days=30):
    """피드백 집계 통계 반환 (총 건수, 평균 rating, label 분포 등)"""
    ph = _p()
    cutoff = datetime.now(timezone.utc).isoformat()[:10]  # today
    # 간단히 days 전 날짜 계산
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as (conn, cur):
        cur.execute(
            f"SELECT * FROM response_feedback WHERE created_at >= {ph} ORDER BY created_at DESC",
            (cutoff,)
        )
        rows = cur.fetchall()

    feedbacks = [_row_to_dict(r) for r in rows]
    total = len(feedbacks)
    if total == 0:
        return {'total': 0, 'avgRating': None, 'avgLegalRating': None,
                'avgQualityRating': None, 'labelDistribution': {}}

    ratings = [f['rating'] for f in feedbacks if f.get('rating') is not None]
    legal_ratings = [f['legal_rating'] for f in feedbacks if f.get('legal_rating') is not None]
    quality_ratings = [f['quality_rating'] for f in feedbacks if f.get('quality_rating') is not None]

    # label 분포 집계
    label_dist = {}
    for f in feedbacks:
        labels = _pg_json_loads_or(f.get('labels_json'), [])
        if isinstance(labels, list):
            for lbl in labels:
                label_dist[lbl] = label_dist.get(lbl, 0) + 1

    return {
        'total': total,
        'avgRating': round(sum(ratings) / len(ratings), 2) if ratings else None,
        'avgLegalRating': round(sum(legal_ratings) / len(legal_ratings), 2) if legal_ratings else None,
        'avgQualityRating': round(sum(quality_ratings) / len(quality_ratings), 2) if quality_ratings else None,
        'labelDistribution': label_dist,
    }


# ─── preference_pairs CRUD ────────────────────────────────────────

def add_preference_pair(prompt, response_chosen, response_rejected,
                        chosen_legal_score=None, rejected_legal_score=None,
                        chosen_consult_score=None, rejected_consult_score=None,
                        chosen_composite=None, rejected_composite=None,
                        label_source='human', labeled_by='',
                        label_confidence=1.0,
                        chosen_msg_id=None, rejected_msg_id=None,
                        conversation_id=None):
    """선호도 쌍 저장"""
    pair_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as (conn, cur):
        cur.execute(
            f"""INSERT INTO preference_pairs
                (id, prompt, response_chosen, response_rejected,
                 chosen_legal_score, rejected_legal_score,
                 chosen_consult_score, rejected_consult_score,
                 chosen_composite, rejected_composite,
                 label_source, labeled_by, label_confidence,
                 chosen_msg_id, rejected_msg_id, conversation_id,
                 exported, exported_at, created_at)
                VALUES ({_ph(19)})""",
            (pair_id, prompt, response_chosen, response_rejected,
             chosen_legal_score, rejected_legal_score,
             chosen_consult_score, rejected_consult_score,
             chosen_composite, rejected_composite,
             label_source, labeled_by, label_confidence,
             chosen_msg_id, rejected_msg_id, conversation_id,
             0, None, now)
        )
    return pair_id


def list_preference_pairs(exported=None, label_source=None,
                          limit=100, offset=0):
    """선호도 쌍 목록 (exported=True/False/None 필터)"""
    ph = _p()
    conditions = []
    params = []
    if exported is not None:
        conditions.append(f"exported = {ph}")
        params.append(1 if exported else 0)
    if label_source is not None:
        conditions.append(f"label_source = {ph}")
        params.append(label_source)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    params.extend([limit, offset])
    with get_conn() as (conn, cur):
        cur.execute(
            f"SELECT * FROM preference_pairs {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
            params
        )
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def mark_preference_pairs_exported(pair_ids: list = None, all_unexported=False):
    """exported=1, exported_at=now() 로 일괄 업데이트.
    all_unexported=True이면 ids 무관하게 exported=0인 모든 레코드를 업데이트."""
    ph = _p()
    now = _now()
    with get_conn() as (conn, cur):
        if all_unexported:
            cur.execute(
                f"UPDATE preference_pairs SET exported = 1, exported_at = {ph} WHERE exported = 0",
                (now,)
            )
            return cur.rowcount
        if not pair_ids:
            return 0
        updated = 0
        for pid in pair_ids:
            cur.execute(
                f"UPDATE preference_pairs SET exported = 1, exported_at = {ph} WHERE id = {ph}",
                (now, pid)
            )
            updated += cur.rowcount
    return updated


def export_preference_pairs_dpo(format='openai', limit=500):
    """
    DPO 학습용 데이터 export
    format='openai' → [{"messages":[...], "chosen":..., "rejected":...}, ...]
    format='hf'     → [{"prompt":..., "chosen":..., "rejected":...}, ...]
    """
    ph = _p()
    with get_conn() as (conn, cur):
        cur.execute(
            f"SELECT * FROM preference_pairs WHERE exported = 0 ORDER BY created_at ASC LIMIT {ph}",
            (limit,)
        )
        rows = cur.fetchall()

    pairs = [_row_to_dict(r) for r in rows]
    result = []

    for p in pairs:
        if format == 'openai':
            result.append({
                'messages': [{'role': 'user', 'content': p['prompt']}],
                'chosen': {'role': 'assistant', 'content': p['response_chosen']},
                'rejected': {'role': 'assistant', 'content': p['response_rejected']},
                'pair_id': p['id'],
            })
        else:  # hf format
            result.append({
                'prompt': p['prompt'],
                'chosen': p['response_chosen'],
                'rejected': p['response_rejected'],
                'pair_id': p['id'],
            })

    return result


# ─── RLHF 통계 ────────────────────────────────────────────────────

def get_rlhf_stats():
    """
    RLHF 관리 페이지용 통계 집계
    반환: total_feedback, total_pairs, exported_pairs,
          avg_composite_reward, label_distribution, daily_feedback
    """
    from datetime import timedelta
    ph = _p()
    now_dt = datetime.now(timezone.utc)
    seven_days_ago = (now_dt - timedelta(days=7)).isoformat()

    with get_conn() as (conn, cur):
        # total feedback
        cur.execute("SELECT COUNT(*) FROM response_feedback")
        total_feedback = cur.fetchone()[0] or 0

        # total pairs
        cur.execute("SELECT COUNT(*) FROM preference_pairs")
        total_pairs = cur.fetchone()[0] or 0

        # exported pairs (SQLite: 1, PostgreSQL: TRUE 모두 호환)
        cur.execute("SELECT COUNT(*) FROM preference_pairs WHERE exported IS NOT NULL AND exported != 0")
        exported_pairs = cur.fetchone()[0] or 0

        # avg composite reward (chosen_composite 평균)
        cur.execute("SELECT AVG(chosen_composite) FROM preference_pairs WHERE chosen_composite IS NOT NULL")
        row = cur.fetchone()
        avg_composite_reward = round(row[0], 4) if row and row[0] is not None else 0.0

        # label_source 별 건수
        cur.execute("SELECT label_source, COUNT(*) FROM preference_pairs GROUP BY label_source")
        label_rows = cur.fetchall()
        label_distribution = {}
        for r in label_rows:
            d = _row_to_dict(r) if hasattr(r, 'keys') else None
            if d:
                label_distribution[d.get('label_source', 'unknown')] = d.get('count', 0)
            else:
                label_distribution[r[0] or 'unknown'] = r[1]

        # 최근 7일 일별 피드백 건수
        if _use_postgres:
            cur.execute(
                f"""SELECT DATE(created_at) as date, COUNT(*) as count
                    FROM response_feedback
                    WHERE created_at >= {ph}
                    GROUP BY DATE(created_at)
                    ORDER BY date""",
                (seven_days_ago,)
            )
        else:
            cur.execute(
                f"""SELECT SUBSTR(created_at, 1, 10) as date, COUNT(*) as count
                    FROM response_feedback
                    WHERE created_at >= {ph}
                    GROUP BY SUBSTR(created_at, 1, 10)
                    ORDER BY date""",
                (seven_days_ago,)
            )
        daily_rows = cur.fetchall()
        daily_feedback = []
        for r in daily_rows:
            d = _row_to_dict(r) if hasattr(r, 'keys') else None
            if d:
                daily_feedback.append({'date': str(d.get('date', '')), 'count': d.get('count', 0)})
            else:
                daily_feedback.append({'date': str(r[0]), 'count': r[1]})

    return {
        'total_feedback': total_feedback,
        'total_pairs': total_pairs,
        'exported_pairs': exported_pairs,
        'avg_composite_reward': avg_composite_reward,
        'label_distribution': label_distribution,
        'daily_feedback': daily_feedback,
    }


# ════════════════════════════════════════
#  모듈 로드 시 자동 초기화
# ════════════════════════════════════════
init_db()

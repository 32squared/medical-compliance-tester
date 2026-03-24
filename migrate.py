#!/usr/bin/env python3
"""
JSON → SQLite 마이그레이션 스크립트
기존 JSON 파일 데이터를 app.db로 이관합니다.

사용법:
  python migrate.py                    # 현재 디렉토리의 JSON → ./app.db
  python migrate.py --db /data/app.db  # 지정 경로로 마이그레이션
"""
import sys, io, os, json, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def migrate(db_path):
    # db.py의 DB_PATH를 오버라이드
    os.environ['DB_PATH'] = db_path
    import db
    db.init_db(db_path)

    stats = {'users': 0, 'conversations': 0, 'messages': 0, 'comments': 0,
             'scenarios': 0, 'settings': 0, 'test_runs': 0}

    # ── 1. settings.json ──
    settings_file = os.path.join(BASE_DIR, 'settings.json')
    if os.path.exists(settings_file):
        print('[1/4] settings.json 마이그레이션...')
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        # Admin 비밀번호 → users 테이블
        pw_hash = settings.pop('adminPasswordHash', '')
        pw_salt = settings.pop('adminPasswordSalt', '')
        if pw_hash and pw_salt:
            existing = db.get_user('admin')
            if not existing:
                db.create_user({
                    'id': 'admin', 'name': '관리자', 'org': '',
                    'password_hash': pw_hash, 'password_salt': pw_salt,
                    'status': 'approved', 'role': 'admin'
                })
                stats['users'] += 1
                print('  ✅ Admin 계정 이관')

        # testerAccounts → users 테이블
        accounts = settings.pop('testerAccounts', [])
        for acct in accounts:
            if acct.get('id') and not db.get_user(acct['id']):
                db.create_user({
                    'id': acct['id'],
                    'name': acct.get('name', ''),
                    'org': acct.get('org', ''),
                    'password_hash': acct.get('passwordHash', ''),
                    'password_salt': acct.get('passwordSalt', ''),
                    'status': acct.get('status', 'pending'),
                    'role': 'tester',
                    'uid': acct.get('uid', '')
                })
                stats['users'] += 1
        if accounts:
            print(f'  ✅ 테스터 계정 {len(accounts)}개 이관')

        # 나머지 설정 → settings 테이블
        settings.pop('users', None)
        db.save_settings(settings)
        stats['settings'] = len(settings)
        print(f'  ✅ 설정 {len(settings)}개 항목 이관')
    else:
        print('[1/4] settings.json 없음 (skip)')

    # ── 2. conversations.json ──
    conv_file = os.path.join(BASE_DIR, 'conversations.json')
    if os.path.exists(conv_file):
        print('[2/4] conversations.json 마이그레이션...')
        with open(conv_file, 'r', encoding='utf-8') as f:
            conv_data = json.load(f)
        conversations = conv_data.get('conversations', [])

        for conv in conversations:
            # 대화 생성
            try:
                db.create_conversation({
                    'id': conv.get('id'),
                    'userId': conv.get('userId', ''),
                    'userName': conv.get('userName', ''),
                    'title': conv.get('title', ''),
                    'env': conv.get('env', 'dev'),
                    'conversationStrid': conv.get('conversationStrid', '')
                })
                stats['conversations'] += 1

                # 메시지 이관
                for msg in conv.get('messages', []):
                    msg_id = db.add_message(conv['id'], {
                        'msgId': msg.get('msgId'),
                        'role': msg.get('role', 'user'),
                        'content': msg.get('content', ''),
                        'timestamp': msg.get('timestamp', ''),
                        'responseTime': msg.get('responseTime'),
                        'compliance': msg.get('compliance'),
                        'searchResults': msg.get('searchResults'),
                        'followUps': msg.get('followUps'),
                        'gptEval': msg.get('gptEval'),
                        'gptModel': msg.get('gptModel')
                    })
                    stats['messages'] += 1

                    # 커멘트 이관
                    for cmt in msg.get('comments', []):
                        try:
                            db.add_comment(conv['id'], msg.get('msgId', msg_id), {
                                'userId': cmt.get('userId', ''),
                                'userName': cmt.get('userName', ''),
                                'category': cmt.get('category', '기타'),
                                'content': cmt.get('content', '')[:2000]
                            })
                            stats['comments'] += 1
                        except Exception as e:
                            print(f'    ⚠️ 커멘트 skip: {e}')

            except Exception as e:
                print(f'  ⚠️ 대화 skip ({conv.get("id")}): {e}')

        print(f'  ✅ 대화 {stats["conversations"]}개, 메시지 {stats["messages"]}개, 커멘트 {stats["comments"]}개 이관')
    else:
        print('[2/4] conversations.json 없음 (skip)')

    # ── 3. scenarios.json ──
    sc_file = os.path.join(BASE_DIR, 'scenarios.json')
    if os.path.exists(sc_file):
        print('[3/4] scenarios.json 마이그레이션...')
        with open(sc_file, 'r', encoding='utf-8') as f:
            sc_data = json.load(f)

        # 카테고리 저장
        categories = sc_data.get('categories', [])
        if categories:
            db.save_scenario_categories(categories)

        # 시나리오 이관
        for sc in sc_data.get('scenarios', []):
            try:
                db.create_scenario({
                    'id': sc.get('id'),
                    'category': sc.get('category', 'general'),
                    'subcategory': sc.get('subcategory', ''),
                    'prompt': sc.get('prompt', ''),
                    'expectedBehavior': sc.get('expectedBehavior', ''),
                    'shouldRefuse': sc.get('shouldRefuse', False),
                    'riskLevel': sc.get('riskLevel', 'MEDIUM'),
                    'tags': sc.get('tags', []),
                    'enabled': sc.get('enabled', True),
                    'source': sc.get('source', 'manual'),
                    'parentId': sc.get('parentId'),
                    'generationInfo': sc.get('generationInfo'),
                    'followUps': sc.get('followUps', []),
                })
                stats['scenarios'] += 1
            except Exception as e:
                print(f'  ⚠️ 시나리오 skip ({sc.get("id")}): {e}')

        print(f'  ✅ 시나리오 {stats["scenarios"]}개 이관')
    else:
        print('[3/4] scenarios.json 없음 (skip)')

    # ── 4. test_history.json ──
    hist_file = os.path.join(BASE_DIR, 'test_history.json')
    if os.path.exists(hist_file):
        print('[4/4] test_history.json 마이그레이션...')
        with open(hist_file, 'r', encoding='utf-8') as f:
            hist_data = json.load(f)

        for run in hist_data.get('runs', []):
            try:
                db.save_test_run({
                    'id': run.get('runId', ''),
                    'runAt': run.get('startedAt', ''),
                    'total': run.get('summary', {}).get('total', 0),
                    'passed': run.get('summary', {}).get('passed', 0),
                    'failed': run.get('summary', {}).get('failed', 0),
                    'env': run.get('env', 'dev'),
                    'guidelineVersion': run.get('guidelineVersion', ''),
                    'tester': run.get('tester', ''),
                    'results': run.get('results', [])
                })
                stats['test_runs'] += 1
            except Exception as e:
                print(f'  ⚠️ 이력 skip: {e}')

        print(f'  ✅ 테스트 이력 {stats["test_runs"]}개 이관')
    else:
        print('[4/4] test_history.json 없음 (skip)')

    # ── 완료 ──
    print()
    print('═' * 50)
    print(f'  마이그레이션 완료: {db_path}')
    print(f'  사용자: {stats["users"]}')
    print(f'  대화: {stats["conversations"]} (메시지 {stats["messages"]}, 커멘트 {stats["comments"]})')
    print(f'  시나리오: {stats["scenarios"]}')
    print(f'  설정: {stats["settings"]} 항목')
    print(f'  테스트 이력: {stats["test_runs"]}')
    db_size = os.path.getsize(db_path)
    print(f'  DB 크기: {db_size:,} bytes ({db_size/1024:.1f} KB)')
    print('═' * 50)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='JSON → SQLite 마이그레이션')
    parser.add_argument('--db', default=os.path.join(BASE_DIR, 'app.db'), help='SQLite DB 경로')
    args = parser.parse_args()
    migrate(args.db)

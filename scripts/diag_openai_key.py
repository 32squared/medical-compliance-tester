import os
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(os.environ['DATABASE_URL'])
with conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("SELECT key, value FROM settings WHERE key ILIKE '%openai%' OR key ILIKE '%gpt%' OR key ILIKE '%api%' OR key ILIKE '%key%'")
    rows = cur.fetchall()
    print(f'matched rows: {len(rows)}', flush=True)
    for r in rows:
        v = r['value']
        s = str(v) if v is not None else ''
        masked = '****' in s
        prefix = (s[:25] + '...') if len(s) > 25 else s
        print(f"  key={r['key']!r}  masked={masked}  preview={prefix}", flush=True)

    cur.execute("SELECT key FROM settings ORDER BY key")
    all_keys = [r['key'] for r in cur.fetchall()]
    print(f'\n전체 settings 키 ({len(all_keys)}개):', flush=True)
    for k in all_keys:
        print(f'  - {k}', flush=True)

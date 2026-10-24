"""Recover missing Seedance 2.5 trend links. Dry-run by default; --apply writes.

Run inside the deployed container with DATABASE_URL already configured. No
provider calls, charges or status updates. Existing links always win.
"""
from __future__ import annotations

import argparse
import json
import os

import psycopg


def source_trend_id(raw):
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict) or data.get('action_type') != 'trend':
            return None
        trend_id = data.get('trend_id')
        if type(trend_id) is not int or trend_id <= 0:
            return None
        if 'prompt_source_id' in data:
            if data['prompt_source_id'] != trend_id:
                return None
        elif data.get('source') != 'trend':
            # Older dedicated launches persisted source + trend_id only.
            return None
        return trend_id
    except (ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    scanned = eligible = inserted = 0
    after_id = 0
    with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=10,
                          options='-c statement_timeout=15000 -c lock_timeout=3000') as conn:
        while True:
            rows = conn.execute('''SELECT g.id, g.task_id, g.user_id, g.request_data, g.created_at
                FROM generation_tasks g LEFT JOIN trend_generation_runs r ON r.task_id=g.task_id
                WHERE g.model='seedance_2_5' AND g.id > %s AND r.task_id IS NULL
                ORDER BY g.id LIMIT 500''', (after_id,)).fetchall()
            if not rows:
                break
            for row_id, task_id, user_id, raw, created_at in rows:
                scanned += 1
                after_id = row_id
                trend_id = source_trend_id(raw)
                if trend_id is None:
                    continue
                row = conn.execute('SELECT tags FROM user_prompts WHERE id=%s', (trend_id,)).fetchone()
                if not row:
                    continue
                tags = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                if not isinstance(tags, list) or 'trend' not in tags:
                    continue
                eligible += 1
                if args.apply:
                    inserted += conn.execute('''INSERT INTO trend_generation_runs
                        (task_id, trend_id, user_id, created_at) VALUES (%s,%s,%s,%s)
                        ON CONFLICT (task_id) DO NOTHING''',
                        (task_id, trend_id, user_id, created_at)).rowcount
            conn.commit()
    print(json.dumps({'apply': args.apply, 'scanned': scanned, 'eligible': eligible, 'inserted': inserted}))


if __name__ == '__main__':
    main()

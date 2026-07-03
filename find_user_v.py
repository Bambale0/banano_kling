#!/usr/bin/env python3
"""Find user V in the bot database."""
import sqlite3, os

os.chdir("/root/tanya/banano_kling")
for db_name in ["banano_bot.db", "bot.db", "database.db", "data/database.db", "banano.db"]:
    if os.path.exists(db_name):
        print("Using:", db_name)
        conn = sqlite3.connect(db_name)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Users with 4 published
        c.execute("""
            SELECT u.id, u.telegram_id, u.first_name, u.username,
                   COUNT(gt.id) as total,
                   SUM(CASE WHEN gt.is_public_feed = 1 THEN 1 ELSE 0 END) as pub
            FROM users u
            LEFT JOIN generation_tasks gt ON gt.user_id = u.id 
                AND gt.status = 'completed'
                AND gt.result_url IS NOT NULL
            GROUP BY u.id
            HAVING pub = 4
            ORDER BY total DESC
            LIMIT 15
        """)
        rows = c.fetchall()
        if rows:
            for r in rows:
                name = r["first_name"] or r["username"] or "?"
                print("  id=%s tg=%s name=%s total=%s pub=%s" % (r["id"], r["telegram_id"], name, r["total"], r["pub"]))
        else:
            print("  No users with pub=4")

        # Also users starting with common letters
        c.execute("""
            SELECT u.id, u.telegram_id, u.first_name, u.username,
                   COUNT(gt.id) as total,
                   SUM(CASE WHEN gt.is_public_feed = 1 THEN 1 ELSE 0 END) as pub
            FROM users u
            LEFT JOIN generation_tasks gt ON gt.user_id = u.id 
                AND gt.status = 'completed'
                AND gt.result_url IS NOT NULL
            GROUP BY u.id
            HAVING total > 5 AND pub < 5
            ORDER BY total DESC
            LIMIT 10
        """)
        rows2 = c.fetchall()
        if rows2:
            print("Users with >5 completed but <5 published:")
            for r in rows2:
                name = r["first_name"] or r["username"] or "?"
                print("  id=%s tg=%s name=%s total=%s pub=%s" % (r["id"], r["telegram_id"], name, r["total"], r["pub"]))

        conn.close()
        break

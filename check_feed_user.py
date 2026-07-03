#!/usr/bin/env python3
"""Check feed data for a specific user."""
import sqlite3
import sys
import os

os.chdir("/root/tanya/banano_kling")
sys.path.insert(0, "/root/tanya/banano_kling")

# Find the database
db_path = None
for path in ["tgbanana.db", "data/tgbanana.db"]:
    if os.path.exists(path):
        db_path = path
        break

if not db_path:
    print("DB not found")
    sys.exit(1)

print("Using DB:", db_path)
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Check if a specific user_id was passed
user_id = None
if len(sys.argv) > 1:
    try:
        user_id = int(sys.argv[1])
    except ValueError:
        pass

if user_id:
    # Check specific user
    c.execute("SELECT id, user_id, telegram_id, first_name, username FROM users WHERE user_id = ? OR id = ?", (user_id, user_id))
    user = c.fetchone()
    if user:
        print("\nUser:", dict(user))
        uid = user["id"]
        c.execute("SELECT COUNT(*) FROM generation_tasks WHERE user_id = ? AND status = 'completed' AND result_url IS NOT NULL", (uid,))
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM generation_tasks WHERE user_id = ? AND is_public_feed = 1", (uid,))
        pub = c.fetchone()[0]
        print("Total completed:", total)
        print("Published to feed:", pub)
        
        c.execute("SELECT id, type, model, is_public_feed, created_at, result_url FROM generation_tasks WHERE user_id = ? AND status = 'completed' AND result_url IS NOT NULL ORDER BY created_at DESC LIMIT 10", (uid,))
        tasks = c.fetchall()
        print("Recent tasks:")
        for t in tasks:
            print("  task_id=%s type=%s model=%s pub=%s created=%s" % (
                t["id"], t["type"], t["model"], t["is_public_feed"], t["created_at"]
            ))
    else:
        print("User not found")
else:
    # Show stats
    c.execute("SELECT COUNT(*) FROM users")
    print("Total users:", c.fetchone()[0])
    
    c.execute("SELECT COUNT(*) FROM generation_tasks WHERE is_public_feed = 1")
    print("Total published items:", c.fetchone()[0])
    
    c.execute("SELECT COUNT(DISTINCT user_id) FROM generation_tasks WHERE is_public_feed = 1")
    print("Unique users who published:", c.fetchone()[0])
    
    # Users with >5 completed but <5 published
    query = """
        SELECT u.id as uid, u.telegram_id, u.first_name, u.username,
               COUNT(gt.id) as total_completed,
               SUM(CASE WHEN gt.is_public_feed = 1 THEN 1 ELSE 0 END) as published
        FROM users u
        LEFT JOIN generation_tasks gt ON gt.user_id = u.id 
            AND gt.status = 'completed'
            AND gt.result_url IS NOT NULL
        GROUP BY u.id
        HAVING total_completed > 5 AND published < 5
        ORDER BY total_completed DESC
        LIMIT 10
    """
    c.execute(query)
    rows = c.fetchall()
    if rows:
        print("\nUsers with >5 completed tasks but <5 published:")
        for r in rows:
            name = r["first_name"] or r["username"] or "?"
            print("  ID=%d (%s) total=%d pub=%d" % (r["uid"], name, r["total_completed"], r["published"]))
    else:
        print("No users with mismatch")

conn.close()

import sqlite3
import asyncio

conn = sqlite3.connect('/root/banano_kling/bot.db')
cur = conn.cursor()
cur.execute('''
CREATE TABLE IF NOT EXISTS partner_withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount_rub REAL NOT NULL,
    method TEXT NOT NULL,
    requisites TEXT,
    status TEXT DEFAULT 'requested',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
)
''')
conn.commit()
print('table_exists', cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='partner_withdrawals'").fetchone()[0])
conn.close()

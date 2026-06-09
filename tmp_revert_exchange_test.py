import sqlite3

conn = sqlite3.connect('/root/banano_kling/bot.db')
cur = conn.cursor()
cur.execute(
    '''
    UPDATE users
    SET credits = credits - 1,
        partner_balance_rub = partner_balance_rub + 10,
        updated_at = CURRENT_TIMESTAMP
    WHERE telegram_id = ?
    ''',
    (339795159,),
)
conn.commit()
cur.execute('SELECT credits, partner_balance_rub FROM users WHERE telegram_id = ?', (339795159,))
print(cur.fetchone())
conn.close()

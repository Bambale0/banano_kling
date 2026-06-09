import asyncio
import sqlite3
from bot.database import exchange_partner_balance_to_credits

TELEGRAM_ID = 339795159
AMOUNT = 10
RATE = 10

async def main():
    result = await exchange_partner_balance_to_credits(TELEGRAM_ID, AMOUNT, RATE)
    print('exchange_result', result)
    if not result.get('ok'):
        return
    conn = sqlite3.connect('/root/banano_kling/bot.db')
    cur = conn.cursor()
    cur.execute(
        '''
        UPDATE users
        SET credits = credits - ?,
            partner_balance_rub = partner_balance_rub + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_id = ?
        ''',
        (result['credits_added'], result['debited_rub'], TELEGRAM_ID),
    )
    conn.commit()
    cur.execute('SELECT credits, partner_balance_rub FROM users WHERE telegram_id = ?', (TELEGRAM_ID,))
    print('after_revert', cur.fetchone())
    conn.close()

asyncio.run(main())

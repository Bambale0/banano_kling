import asyncio
from bot.database import exchange_partner_balance_to_credits

async def main():
    result = await exchange_partner_balance_to_credits(339795159, 10, 10)
    print(result)

asyncio.run(main())

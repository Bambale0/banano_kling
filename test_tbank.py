import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

from bot.services.tbank_service import tbank_service


async def test_init_payment():
    """Test T-Bank payment creation"""
    try:
        result = await tbank_service.init_payment(
            amount=10000,  # 100 RUB
            order_id="test_order_123",
            description="Test payment",
            customer_key="test_customer_123",
            success_url="https://t.me/BananaBoombot_bot?start=success_test",
            fail_url="https://t.me/BananaBoombot_bot?start=fail_test",
            notification_url="https://dev.chillcreative.ru/tbank/webhook",
        )
        print("Result:", result)
        if result and result.get("Success"):
            print("SUCCESS! PaymentId:", result.get("PaymentId"))
            print("PaymentURL:", result.get("PaymentURL"))
        else:
            print("ERROR:", result)
    except Exception as e:
        print("Exception:", str(e))


asyncio.run(test_init_payment())

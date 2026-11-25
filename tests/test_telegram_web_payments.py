from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.payment_platform_policy import vk_payment_provider_denied


@pytest.mark.parametrize('platform', ['telegram', 'web'])
@pytest.mark.parametrize('provider', ['telegram_stars', 'lava_card', 'lava_sbp', 'lava_foreign_paypal', 'freekassa_card', 'freekassa_sbp', 'cryptobot', 'tribute'])
def test_existing_methods_allowed_on_telegram_and_web(platform, provider):
    assert vk_payment_provider_denied({'platform': platform}, provider) is None


def test_vk_scope_unchanged():
    assert vk_payment_provider_denied({'platform': 'vk'}, 'telegram_stars').status == 403
    assert vk_payment_provider_denied({'platform': 'vk'}, 'lava_card') is None


@pytest.mark.parametrize('callback', ['menu_balance', 'buy_lava_card_mini', 'freekassa_sbp_mini', 'buy_crypto_mini', 'choose_pay_mini'])
async def test_bot_callbacks_reach_existing_handlers(callback):
    from aiogram.types import CallbackQuery, User

    from bot.telegram_payment_surface import TelegramPaymentSurfaceMiddleware
    event = CallbackQuery(id='test', from_user=User(id=123, is_bot=False, first_name='test'), chat_instance='test', data=callback)
    handler = AsyncMock()
    await TelegramPaymentSurfaceMiddleware()(handler, event, {})
    handler.assert_awaited_once_with(event, {})


async def test_outgoing_keyboard_preserves_callbacks_and_signed_checkout_url():
    from aiogram.methods import SendMessage
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from bot.telegram_payment_surface import TelegramPaymentRequestMiddleware
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Card', callback_data='buy_lava_card_mini'),
        InlineKeyboardButton(text='Checkout', url='https://gate.lava.top/pay/fixture?signature=synthetic'),
    ]])
    method = SendMessage(chat_id=123, text='Checkout', reply_markup=markup)
    send = AsyncMock()
    await TelegramPaymentRequestMiddleware()(send, AsyncMock(), method)
    assert send.await_args.args[1] is method
    assert method.reply_markup is markup


async def test_native_non_xtr_invoice_is_rejected():
    from aiogram.methods import CreateInvoiceLink
    from aiogram.types import LabeledPrice

    from bot.telegram_payment_surface import TelegramPaymentRequestMiddleware

    method = CreateInvoiceLink(title='test', description='test', payload='test', currency='RUB', prices=[LabeledPrice(label='test', amount=100)])
    send = AsyncMock()
    with pytest.raises(ValueError, match='XTR'):
        await TelegramPaymentRequestMiddleware()(send, AsyncMock(), method)
    send.assert_not_awaited()


async def test_successful_stars_reaches_settlement_even_in_legacy_lava_email_state():
    from datetime import UTC, datetime

    from aiogram.types import Chat, Message, SuccessfulPayment

    from bot.states import PaymentStates
    from bot.telegram_payment_surface import TelegramPaymentSurfaceMiddleware

    payment = SuccessfulPayment(currency='XTR', total_amount=10, invoice_payload='stars:order:10', telegram_payment_charge_id='charge', provider_payment_charge_id='')
    event = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=123, type='private'), successful_payment=payment)
    settlement = AsyncMock(return_value='settled')
    state = AsyncMock()
    result = await TelegramPaymentSurfaceMiddleware()(settlement, event, {'raw_state': PaymentStates.waiting_lava_email.state, 'state': state})
    assert result == 'settled'
    settlement.assert_awaited_once()
    state.clear.assert_not_awaited()


async def test_dispatcher_settles_stars_before_legacy_email_catchall(monkeypatch):
    from datetime import UTC, datetime

    from aiogram import Bot, Dispatcher, Router
    from aiogram.types import Chat, Message, SuccessfulPayment, Update, User

    from bot import main
    from bot.handlers import payments
    from bot.states import PaymentStates
    from bot.telegram_payment_surface import install_telegram_payment_surface

    settle = AsyncMock()
    async def settlement(message):
        await settle(message)

    monkeypatch.setattr(payments, 'process_successful_stars_payment', settlement)
    banned = AsyncMock(return_value=True)
    maintenance = AsyncMock(return_value=True)
    subscription = AsyncMock(return_value=True)
    monkeypatch.setattr(main, 'is_user_banned', banned)
    monkeypatch.setattr(main, 'is_maintenance_mode_enabled', maintenance)
    monkeypatch.setattr(main, 'is_channel_subscription_required', subscription)
    dp = Dispatcher()
    dp.message.outer_middleware(main.AccessGuardMiddleware())
    install_telegram_payment_surface(dp)
    legacy = Router()
    catchall = AsyncMock()
    async def legacy_email(message):
        await catchall(message)

    legacy.message.register(legacy_email, PaymentStates.waiting_lava_email)
    dp.include_router(legacy)
    bot = Bot('123456:TEST_TOKEN')
    try:
        state = dp.fsm.get_context(bot=bot, chat_id=123, user_id=123)
        await state.set_state(PaymentStates.waiting_lava_email)
        message = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=123, type='private'), from_user=User(id=123, is_bot=False, first_name='test'), successful_payment=SuccessfulPayment(currency='XTR', total_amount=10, invoice_payload='stars:order:10', telegram_payment_charge_id='charge', provider_payment_charge_id=''))
        await dp.feed_update(bot, Update(update_id=1, message=message))
        settle.assert_awaited_once()
        catchall.assert_not_awaited()
        banned.assert_not_awaited()
        maintenance.assert_not_awaited()
        subscription.assert_not_awaited()
    finally:
        await bot.session.close()
        await dp.storage.close()


@pytest.mark.parametrize('text', [' ', '\n\t', '/start ', '/start@Bot '])
async def test_empty_message_or_start_argument_does_not_crash(text):
    from datetime import UTC, datetime

    from aiogram.types import Chat, Message

    from bot.telegram_payment_surface import TelegramPaymentSurfaceMiddleware

    event = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=123, type='private'), text=text)
    handler = AsyncMock()
    await TelegramPaymentSurfaceMiddleware()(handler, event, {})
    handler.assert_awaited_once()


@pytest.mark.parametrize('query_id', ['tg_native', 'browser_signed_fixture', 'webstudio_verified-session-abcdef123456'])
@pytest.mark.parametrize('provider', ['freekassa_card', 'freekassa_sbp'])
async def test_miniapp_checkout_uses_authenticated_owner_and_config_price(monkeypatch, query_id, provider):
    import json

    from bot import miniapp
    from bot.handlers import freekassa_payments
    from bot.handlers import miniapp_lava_payment_methods_compat as compat
    compat.install_miniapp_lava_payment_methods()
    context = AsyncMock(return_value=(123, {'platform': 'telegram', 'payload': {'query_id': query_id}, 'user': SimpleNamespace(id=9)}))
    monkeypatch.setattr(miniapp, '_get_user_context', context)
    monkeypatch.setattr(compat.freekassa_service, 'api_enabled', True)
    monkeypatch.setattr(miniapp.preset_manager, 'get_package', lambda key: {'id': key, 'name': 'Fixture', 'credits': 50, 'bonus_credits': 5, 'price_rub': 517})
    transaction = AsyncMock(return_value=True)
    monkeypatch.setattr(miniapp, 'create_transaction', transaction)
    monkeypatch.setattr(freekassa_payments, '_checkout_url', lambda order, method: 'https://checkout.synthetic.test/' + order)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={'init_data': 'signed-fixture', 'package_id': 'fixture', 'provider': provider, 'user_id': 999, 'amount_rub': 1, 'credits': 99999}))
    response = await miniapp.miniapp_create_payment(request)
    assert response.status == 200
    result = json.loads(response.text)
    assert result['payment_url'].startswith('https://checkout.synthetic.test/')
    assert result['credits'] == 55
    assert transaction.await_args.kwargs['user_id'] == 9
    assert transaction.await_args.kwargs['amount_rub'] == 517
    assert transaction.await_args.kwargs['status'] == 'pending'
    assert context.await_args.args[1] == 'signed-fixture'


@pytest.mark.parametrize('text', ['/balance', '/wallet', '/topup', '/pay', '/start buy_lava_card_mini', 'buyer@synthetic.test'])
async def test_bot_payment_commands_and_existing_email_state_are_preserved(text):
    from datetime import UTC, datetime

    from aiogram.types import Chat, Message

    from bot.states import PaymentStates
    from bot.telegram_payment_surface import TelegramPaymentSurfaceMiddleware
    event = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=123, type='private'), text=text)
    state = AsyncMock()
    handler = AsyncMock()
    data = {'state': state, 'raw_state': PaymentStates.waiting_lava_email.state}
    await TelegramPaymentSurfaceMiddleware()(handler, event, data)
    handler.assert_awaited_once_with(event, data)
    state.clear.assert_not_awaited()

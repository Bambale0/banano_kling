import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from bot.payment_platform_policy import vk_payment_provider_denied


@pytest.mark.parametrize('provider', ['lava', 'lava_card', 'lava_sbp', 'lava_foreign_paypal', 'freekassa_card', 'freekassa_sbp', 'yookassa', 'cryptobot', 'tribute'])
async def test_http_payment_guard_runs_before_provider_or_transaction(monkeypatch, provider):
    from bot import miniapp
    from bot.handlers.miniapp_lava_payment_methods_compat import (
        install_miniapp_lava_payment_methods,
    )

    install_miniapp_lava_payment_methods()
    context = AsyncMock(return_value=(123, {'platform': 'telegram', 'payload': {'query_id': 'tg'}, 'user': SimpleNamespace(id=9)}))
    transaction = AsyncMock()
    invoice = AsyncMock()
    monkeypatch.setattr(miniapp, '_get_user_context', context)
    monkeypatch.setattr(miniapp, 'create_transaction', transaction)
    monkeypatch.setattr(miniapp.lava_service, 'create_invoice', invoice)
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={'init_data': 'verified-by-context', 'provider': provider, 'package_id': 'mini', 'platform': 'web', 'query_id': 'browser_forged'}))
    response = await miniapp.miniapp_create_payment(request)
    assert response.status == 403
    transaction.assert_not_awaited()
    invoice.assert_not_awaited()


def test_bot_buttons_use_website_without_auth_credentials(monkeypatch):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from bot.config import config
    from bot.telegram_payment_surface import website_payment_markup

    monkeypatch.setattr(config, 'MINI_APP_URL', 'https://neuromixbot.com/mini-app/')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Balance', callback_data='menu_balance'),
        InlineKeyboardButton(text='Card', callback_data='buy_lava_card_mini'),
        InlineKeyboardButton(text='Stars', callback_data='buy_stars_mini'),
        InlineKeyboardButton(text='Status', callback_data='check_payment_123'),
        InlineKeyboardButton(text='Foreign', url='https://web.tribute.tg/p/Dxi'),
    ]])
    buttons = website_payment_markup(keyboard).inline_keyboard[0]
    for button in (buttons[0], buttons[1], buttons[4]):
        parsed = urlsplit(button.url)
        assert parsed.netloc == 'neuromixbot.com'
        assert parsed.path == '/login'
        assert 'init_data' not in button.url
    destination = parse_qs(urlsplit(buttons[1].url).query)['return_to'][0]
    assert parse_qs(urlsplit(destination).query) == {'intent': ['topup'], 'package_id': ['mini'], 'provider': ['lava_card']}
    assert buttons[2].callback_data == 'buy_stars_mini'
    assert buttons[3].callback_data == 'check_payment_123'
    tribute_destination = parse_qs(urlsplit(buttons[4].url).query)['return_to'][0]
    assert parse_qs(urlsplit(tribute_destination).query) == {
        'intent': ['topup'], 'package_id': ['mini'], 'provider': ['tribute'],
    }


async def test_bot_old_callback_never_reaches_checkout():
    from datetime import UTC, datetime

    from aiogram.types import CallbackQuery, Chat, Message, User

    from bot.telegram_payment_surface import TelegramPaymentSurfaceMiddleware

    event = CallbackQuery(id='test', from_user=User(id=123, is_bot=False, first_name='test'), chat_instance='test', data='buy_lava_card_mini', message=Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=123, type='private')))
    handler = AsyncMock()
    # Bind a fake Bot API at the model seam; no Telegram network calls.
    bot = AsyncMock()
    event = event.as_(bot)
    event.message.as_(bot)
    await TelegramPaymentSurfaceMiddleware()(handler, event, {})
    handler.assert_not_awaited()
    assert bot.call_count == 2


async def test_native_non_xtr_invoice_is_rejected():
    from aiogram.methods import CreateInvoiceLink
    from aiogram.types import LabeledPrice

    from bot.telegram_payment_surface import TelegramPaymentRequestMiddleware

    method = CreateInvoiceLink(title='test', description='test', payload='test', currency='RUB', prices=[LabeledPrice(label='test', amount=100)])
    send = AsyncMock()
    with pytest.raises(ValueError, match='XTR'):
        await TelegramPaymentRequestMiddleware()(send, AsyncMock(), method)
    send.assert_not_awaited()


async def test_legacy_email_handoff_retains_package_method_and_selected_promo():
    from datetime import UTC, datetime

    from aiogram.types import Chat, Message

    from bot.states import PaymentStates
    from bot.telegram_payment_surface import TelegramPaymentSurfaceMiddleware

    bot = AsyncMock()
    message = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=123, type='private'), text='buyer@synthetic.test').as_(bot)
    state = AsyncMock()
    state.get_data.return_value = {'lava_checkout_package_id': 'mini', 'lava_checkout_mode': 'card', 'promo_code': 'TEST-PROMO'}
    handler = AsyncMock()
    await TelegramPaymentSurfaceMiddleware()(handler, message, {'raw_state': PaymentStates.waiting_lava_email.state, 'state': state})
    handler.assert_not_awaited()
    state.clear.assert_awaited_once()
    link = bot.call_args.args[0].reply_markup.inline_keyboard[0][0].url
    destination = parse_qs(urlsplit(link).query)['return_to'][0]
    assert parse_qs(urlsplit(destination).query) == {'intent': ['topup'], 'package_id': ['mini'], 'provider': ['lava_card'], 'promo_code': ['TEST-PROMO']}


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


@pytest.mark.parametrize('provider', ['lava', 'lava_card', 'lava_sbp', 'lava_foreign_card', 'freekassa', 'freekassa_card', 'yookassa', 'cryptobot', 'robokassa', 'prodamus', 'tribute'])
def test_telegram_cannot_create_non_stars_payment(provider):
    response = vk_payment_provider_denied({'platform': 'telegram', 'payload': {'query_id': 'tg_query'}}, provider)
    assert response is not None
    assert response.status == 403
    assert json.loads(response.text)['code'] == 'WEB_PAYMENT_REQUIRED'


def test_browser_login_and_stars_remain_available():
    assert vk_payment_provider_denied({'platform': 'telegram', 'payload': {'query_id': 'browser_signed_nonce'}}, 'lava_card') is None
    assert vk_payment_provider_denied({'platform': 'telegram'}, 'telegram_stars') is None
    assert vk_payment_provider_denied({'platform': 'vk'}, 'telegram_stars').status == 403
    assert vk_payment_provider_denied({'platform': 'vk'}, 'lava_card') is None


@pytest.mark.parametrize('provider', ['lava_card', 'lava_sbp', 'freekassa_card', 'freekassa_sbp', 'robokassa'])
def test_verified_website_studio_allows_fiat_checkout_only_with_server_bridge_proof(provider):
    ctx = {
        'platform': 'telegram',
        'payload': {'query_id': 'webstudio_verified-session-abcdef123456'},
        'webstudio_session_verified': True,
    }
    assert vk_payment_provider_denied(ctx, provider) is None


@pytest.mark.parametrize('query_id', [
    'tg_native',
    'webstudio_fake',
    'webstudio_',
    'webstudio_verified-session-abcdef123456',
    'webstudio_' + 'a' * 41,
])
def test_unverified_webstudio_and_native_telegram_cannot_pay_with_fiat(query_id):
    ctx = {'platform': 'telegram', 'payload': {'query_id': query_id}}
    assert vk_payment_provider_denied(ctx, 'lava_card').status == 403
    assert vk_payment_provider_denied(ctx | {'webstudio_session_verified': False}, 'freekassa_sbp').status == 403


async def test_outbound_payment_keyboard_uses_current_fsm_promo():
    from aiogram.methods import SendMessage
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from bot.telegram_payment_surface import TelegramPaymentRequestMiddleware

    middleware = TelegramPaymentRequestMiddleware()
    state = SimpleNamespace(get_data=AsyncMock(return_value={'promo_code': 'BONUS50'}))
    middleware.fsm = SimpleNamespace(get_context=lambda **kwargs: state)
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Card', callback_data='buy_lava_card_mini'),
    ]])
    method = SendMessage(chat_id=123, text='Checkout', reply_markup=markup)
    send = AsyncMock()
    await middleware(send, AsyncMock(), method)

    sent = send.await_args.args[1]
    destination = parse_qs(urlsplit(sent.reply_markup.inline_keyboard[0][0].url).query)['return_to'][0]
    assert parse_qs(urlsplit(destination).query) == {
        'intent': ['topup'], 'package_id': ['mini'],
        'provider': ['lava_card'], 'promo_code': ['BONUS50'],
    }
    state.get_data.assert_awaited_once()


async def test_outbound_unrelated_keyboard_does_not_query_fsm():
    from aiogram.methods import SendMessage
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from bot.telegram_payment_surface import TelegramPaymentRequestMiddleware

    middleware = TelegramPaymentRequestMiddleware()
    state = SimpleNamespace(get_data=AsyncMock())
    middleware.fsm = SimpleNamespace(get_context=lambda **kwargs: state)
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='Profile', callback_data='menu_profile'),
    ]])
    method = SendMessage(chat_id=123, text='Profile', reply_markup=markup)
    send = AsyncMock()
    await middleware(send, AsyncMock(), method)

    assert send.await_args.args[1].reply_markup is markup
    state.get_data.assert_not_awaited()

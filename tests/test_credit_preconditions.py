"""Characterization tests: credit function preconditions (Design by Contract).

Pragmatic-programmer: Design by Contract — preconditions must be
checked at function entry before any side effects.
"""

import pytest


class TestAddCreditsPreconditions:
    """add_credits must reject non-positive amounts."""

    @pytest.mark.asyncio
    async def test_add_credits_negative_returns_false(self, mocker):
        from bot.database import add_credits

        mock_db = mocker.patch("bot.database.db_backend")
        result = await add_credits(telegram_id=12345, amount=-5)
        assert result is False
        # DB should NOT have been called
        mock_db.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_credits_zero_returns_false(self, mocker):
        from bot.database import add_credits

        mock_db = mocker.patch("bot.database.db_backend")
        result = await add_credits(telegram_id=12345, amount=0)
        assert result is False
        mock_db.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_credits_positive_works(self, mocker):
        from bot.database import add_credits

        mock_db = mocker.patch("bot.database.db_backend")
        mock_conn = mocker.AsyncMock()
        mock_db.connect.return_value.__aenter__.return_value = mock_conn

        result = await add_credits(telegram_id=12345, amount=10)
        assert result is True
        mock_db.connect.assert_called_once()


class TestDeductCreditsPreconditions:
    """deduct_credits must reject non-positive amounts."""

    @pytest.mark.asyncio
    async def test_deduct_credits_negative_returns_false(self, mocker):
        from bot.database import deduct_credits

        mock_db = mocker.patch("bot.database.db_backend")
        result = await deduct_credits(telegram_id=12345, amount=-5)
        assert result is False
        mock_db.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduct_credits_zero_returns_false(self, mocker):
        from bot.database import deduct_credits

        mock_db = mocker.patch("bot.database.db_backend")
        result = await deduct_credits(telegram_id=12345, amount=0)
        assert result is False
        mock_db.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduct_credits_positive_works(self, mocker):
        from bot.database import deduct_credits

        mock_db = mocker.patch("bot.database.db_backend")
        mock_conn = mocker.AsyncMock()
        mock_conn.execute = mocker.AsyncMock()
        mock_db.connect.return_value.__aenter__.return_value = mock_conn
        # deduct_credits imports config lazily from bot.config.
        mocker.patch("bot.config.config.is_admin", return_value=False)

        result = await deduct_credits(telegram_id=12345, amount=10)
        assert result is False  # Not enough credits, but process reached DB
        mock_db.connect.assert_called_once()


class TestCheckCanAffordType:
    """check_can_afford must accept int (not float)."""

    @pytest.mark.asyncio
    async def test_check_can_afford_accepts_int(self, mocker):
        from bot.database import check_can_afford

        mocker.patch("bot.config.config.is_admin", return_value=False)
        mock_db = mocker.patch("bot.database.db_backend")
        mock_cursor = mocker.AsyncMock()
        mock_cursor.fetchone.return_value = {"credits": 100}
        mock_conn = mocker.AsyncMock()
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__aenter__.return_value = mock_conn
        mock_db.connect.return_value = mock_conn

        result = await check_can_afford(telegram_id=12345, amount=10)
        # True = can afford (100 >= 10)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_can_afford_signature_is_int(self):
        import inspect
        from bot.database import check_can_afford

        sig = inspect.signature(check_can_afford)
        amount_param = sig.parameters["amount"]
        assert amount_param.annotation is int, (
            f"check_can_afford amount should be int, got {amount_param.annotation}"
        )

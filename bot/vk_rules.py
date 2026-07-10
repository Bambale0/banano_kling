import json
import logging

from vkbottle.framework.labeler.base import ABCRule

logger = logging.getLogger(__name__)


def _normalize_payload(payload):
    if payload is None:
        return None

    # Если payload - строка (JSON), распарсим её
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            # Если не JSON - оставляем как строка
            return payload

    # Если после парсинга (или уже был) dict
    if isinstance(payload, dict):
        if "button" in payload:
            return payload.get("button")
        return payload

    # Иначе вернуть строку
    return str(payload) if payload else None


class TextStartsWith(ABCRule):
    def __init__(self, prefix: str):
        self.prefix = prefix.lower()

    async def check(self, event):
        return bool(event.text and event.text.lower().startswith(self.prefix))


class PayloadStartsWith(ABCRule):
    def __init__(self, prefix: str):
        self.prefix = prefix

    async def check(self, event):
        payload = _normalize_payload(getattr(event, "payload", None))
        result = isinstance(payload, str) and payload.startswith(self.prefix)

        if payload is not None:
            logger.info(
                f"[PayloadStartsWith] Prefix={self.prefix!r}, Got={payload!r}, Match={result}"
            )

        return result


class PayloadEq(ABCRule):
    def __init__(self, value):
        self.value = value

    async def check(self, event):
        payload = _normalize_payload(getattr(event, "payload", None))
        expected = _normalize_payload(self.value)
        result = payload == expected

        if payload is not None or expected is not None:
            logger.info(
                f"[PayloadEq] Expected={expected!r}, Got={payload!r}, Match={result}"
            )

        return result


class StateEq(ABCRule):
    """Проверяет что state пользователя равен определённому значению

    Работает с Message объектами которые имеют метод state.get_state()
    """

    def __init__(self, expected_state):
        self.expected_state = expected_state

    async def check(self, event):
        try:
            # Пытаемся получить state события
            if hasattr(event, "state"):
                state = await event.state.get_state()
                result = state == self.expected_state
                return result
            else:
                # Если state недоступен - не совпадает
                return False
        except Exception:
            # При любой ошибке - не совпадает
            return False


class PhotoRule(ABCRule):
    async def check(self, event):
        if hasattr(event, "attachments") and event.attachments:
            return any(
                getattr(att, "type", None) == "photo" for att in event.attachments
            )
        return hasattr(event, "photo") and event.photo is not None


class PeerStateEq(ABCRule):
    """Проверяет state через глобальный state dispenser по peer_id, даже если у event нет .state"""

    def __init__(self, expected_state, state_getter):
        self.expected_state = expected_state
        self.state_getter = state_getter

    async def check(self, event):
        try:
            peer_id = getattr(event, "peer_id", None)
            if peer_id is None:
                return False
            current_state = await self.state_getter(peer_id)
            logger.info(
                f"[PeerStateEq] Expected={self.expected_state!r} ({str(self.expected_state)}), "
                f"Got={current_state!r} ({str(current_state)}), peer_id={peer_id}"
            )

            expected_value = str(
                getattr(self.expected_state, "value", str(self.expected_state))
            )
            current_value = str(current_state) if current_state else ""

            if current_value == expected_value:
                return True

            current_str = str(current_state or "")
            if not current_str.strip():
                return False

            expected_str = str(self.expected_state)
            current_name = getattr(current_state, "__name__", None) or getattr(
                current_state, "name", None
            )
            expected_name = getattr(self.expected_state, "__name__", None) or getattr(
                self.expected_state, "name", None
            )

            return (
                current_str == expected_str
                or (
                    current_name is not None
                    and expected_name is not None
                    and current_name == expected_name
                )
                or current_str.endswith(expected_str)
                or expected_str.endswith(current_str)
            )
        except Exception:
            return False

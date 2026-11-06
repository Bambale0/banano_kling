"""Exact commercial configuration shared by both administrator preview clients."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

MAX_UNITS = 2**63 - 1


class CommercialValidation(ValueError):
    """A safe, administrator-facing validation error."""


def units(value, scale: int, maximum: int = MAX_UNITS) -> int:
    if type(value) not in (str, int):
        raise CommercialValidation('Суммы и проценты указываются точной десятичной строкой.')
    raw = str(value)
    if len(raw) > 64 or not re.fullmatch(r'(0|[1-9][0-9]*)(?:\.[0-9]{1,' + str(scale) + r'})?', raw):
        raise CommercialValidation('Некорректная сумма или точность значения.')
    whole, _, fractional = raw.partition('.')
    result = int(whole) * 10**scale + int(fractional.ljust(scale, '0'))
    if result > maximum:
        raise CommercialValidation('Значение превышает допустимую точность или предел.')
    return result


def exact(value, scale: int, maximum: int = MAX_UNITS) -> str:
    number = units(value, scale, maximum)
    return f'{number // 10**scale}.{number % 10**scale:0{scale}d}'


def key(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9:._/-]{0,119}', value):
        raise CommercialValidation('Некорректный ключ тарифа, группы или цены.')
    return value


def label(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 for c in value):
        raise CommercialValidation('Название должно содержать от 1 до 80 символов без переноса строки.')
    return value.strip()


def object_fields(value, allowed: set[str], required: set[str] | None = None) -> dict:
    if not isinstance(value, dict) or set(value) - allowed or (required or set()) - set(value):
        raise CommercialValidation('Неизвестные или отсутствующие поля настроек.')
    return value


@dataclass(frozen=True)
class Catalog:
    revision: int = 0
    default_tariff_id: str | None = None
    default_partner_group_id: str | None = None
    tariffs: dict = field(default_factory=dict)
    partner_groups: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: dict) -> Catalog:
        object_fields(raw, {'revision', 'default_tariff_id', 'default_partner_group_id', 'tariffs', 'partner_groups'})
        data = asdict(cls()) | raw
        if type(data['revision']) is not int or not 0 <= data['revision'] < MAX_UNITS:
            raise CommercialValidation('Некорректная версия настроек.')
        for collection in ('tariffs', 'partner_groups'):
            if not isinstance(data[collection], dict) or len(data[collection]) > 64:
                raise CommercialValidation('Слишком много тарифов или групп.')
        tariffs, groups, price_count = {}, {}, 0
        for identifier, tariff in data['tariffs'].items():
            key(identifier)
            object_fields(tariff, {'label', 'prices'}, {'label', 'prices'})
            prices = tariff['prices']
            if not isinstance(prices, dict):
                raise CommercialValidation('Цены должны быть набором именованных значений.')
            normalized = {}
            for price_key, price in prices.items():
                key(price_key)
                object_fields(price, {'amount', 'unit'}, {'amount', 'unit'})
                if price['unit'] not in ('job', 'second'):
                    raise CommercialValidation('Единица цены: генерация или секунда.')
                normalized[price_key] = {'amount': exact(price['amount'], 4), 'unit': price['unit']}
                price_count += 1
                if price_count > 512:
                    raise CommercialValidation('Слишком много цен в каталоге.')
            tariffs[identifier] = {'label': label(tariff['label']), 'prices': normalized}
        for identifier, group in data['partner_groups'].items():
            key(identifier)
            object_fields(group, {'label', 'first_level_percent', 'second_level_percent', 'repeat_reward_rub'},
                          {'label', 'first_level_percent', 'second_level_percent', 'repeat_reward_rub'})
            groups[identifier] = {'label': label(group['label']),
                                  'first_level_percent': exact(group['first_level_percent'], 4, 1000000),
                                  'second_level_percent': exact(group['second_level_percent'], 4, 1000000),
                                  'repeat_reward_rub': exact(group['repeat_reward_rub'], 2)}
        for name, collection in [('default_tariff_id', tariffs), ('default_partner_group_id', groups)]:
            if data[name] is not None and data[name] not in collection:
                raise CommercialValidation('Тариф или группа по умолчанию отсутствует в каталоге.')
        return cls(data['revision'], data['default_tariff_id'], data['default_partner_group_id'], tariffs, groups)

    def payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Terms:
    revision: int = 0
    tariff_id: str | None = None
    partner_group_id: str | None = None
    first_level_percent: str | None = None
    second_level_percent: str | None = None
    repeat_reward_rub: str | None = None

    @classmethod
    def parse(cls, raw: dict) -> Terms:
        object_fields(raw, {'revision', 'tariff_id', 'partner_group_id', 'first_level_percent', 'second_level_percent', 'repeat_reward_rub'})
        data = asdict(cls()) | raw
        if type(data['revision']) is not int or not 0 <= data['revision'] < MAX_UNITS:
            raise CommercialValidation('Некорректная версия условий.')
        for name in ('tariff_id', 'partner_group_id'):
            if data[name] is not None:
                key(data[name])
        for name in ('first_level_percent', 'second_level_percent'):
            if data[name] is not None:
                data[name] = exact(data[name], 4, 1000000)
        if data['repeat_reward_rub'] is not None:
            data['repeat_reward_rub'] = exact(data['repeat_reward_rub'], 2)
        return cls(**data)

    def effective(self, catalog: Catalog) -> dict:
        tariff = self.tariff_id or catalog.default_tariff_id
        group = self.partner_group_id or catalog.default_partner_group_id
        if tariff is not None and tariff not in catalog.tariffs:
            raise CommercialValidation('Назначенный тариф отсутствует в каталоге.')
        if group is not None and group not in catalog.partner_groups:
            raise CommercialValidation('Назначенная партнёрская группа отсутствует в каталоге.')
        base = catalog.partner_groups.get(group, {})
        result = {'tariff_id': tariff, 'partner_group_id': group}
        for name in ('first_level_percent', 'second_level_percent', 'repeat_reward_rub'):
            value = getattr(self, name)
            result[name] = value if value is not None else base.get(name)
        return result

    def payload(self) -> dict:
        return asdict(self)


def payment_methods(platform: str) -> list[str]:
    if platform == 'vk':
        # Explicit product ceiling: this rollout reuses the existing Lava shop.
        return ['lava']
    if platform == 'telegram':
        # Telegram methods still come from its existing checkout adapter.
        return []
    raise CommercialValidation('Неизвестная платформа оплаты.')

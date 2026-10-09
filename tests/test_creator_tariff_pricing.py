from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from bot.config import config
from bot.services.preset_manager import preset_manager


@pytest.fixture(autouse=True)
def isolated_database():
    yield


@pytest.fixture
def price_config(monkeypatch):
    value = deepcopy(preset_manager.get_price_config())
    value['creator_tariff'] = {
        'enabled': True,
        'video_models': {
            'seedance_2': {'quality_costs': {'720p': 1.0}},
            'seedance_2_5': {'quality_costs': {'480p': 1.5, '720p': 2.0}},
        },
    }
    monkeypatch.setattr(preset_manager, '_price_config', value)
    return value


def test_creator_rates_are_per_model_quality_and_duration(price_config):
    from bot.creator_tariff import resolve_video_quote
    assert resolve_video_quote('seedance_2', 10, tariff='creator').cost == 10
    assert resolve_video_quote('seedance_2_5', 10, '720p', tariff='creator').cost == 20
    assert resolve_video_quote('seedance-2.5', 6, '480p', tariff='creator').cost == 9


def test_creator_video_reference_multiplier_applies_exactly_once(price_config):
    from bot.creator_tariff import resolve_video_quote
    quote = resolve_video_quote('seedance_2_5', 10, '720p', ['one', 'two'], tariff='creator')
    assert quote.cost == 40
    assert quote.charge_cost == 40
    assert quote.to_dict()['reference_multiplier'] == 2


def test_standard_and_admin_are_preserved(price_config):
    from bot.creator_tariff import resolve_video_quote
    ordinary = preset_manager.get_video_cost_with_quality('seedance_2_5', 10, '720p')
    assert resolve_video_quote('seedance_2_5', 10, '720p').cost == ordinary
    quote = resolve_video_quote('seedance_2_5', 10, '720p', tariff='admin')
    assert quote.cost == ordinary
    assert quote.charge_cost == 0
    assert quote.profile == 'admin'


def test_wan_prime_requires_configured_quality_rate_and_reserves_auto_max(price_config):
    from bot.creator_tariff import resolve_video_quote

    with pytest.raises(ValueError):
        resolve_video_quote('wan_3_prime', 5, '1080p')
    admin_quote = resolve_video_quote('wan_3_prime', 5, '1080p', tariff='admin')
    assert admin_quote.cost == 0
    assert admin_quote.charge_cost == 0
    assert admin_quote.profile == 'admin'

    price_config['costs_reference']['video_models']['wan_3_prime'] = {
        'default_duration': 5,
        'duration_min': 2,
        'duration_max': 30,
        'quality_costs': {'1080p': 3.0},
    }
    quote = resolve_video_quote('wan/3-0-video-prime', -1, '1080P')

    assert quote.model == 'wan_3_prime'
    assert quote.duration == 30
    assert quote.cost == 90
    assert quote.reference_multiplier == 1


def test_disabled_unconfigured_and_non_seedance_fall_back_to_standard(price_config):
    from bot.creator_tariff import resolve_video_quote
    price_config['creator_tariff']['enabled'] = False
    q = resolve_video_quote('seedance_2', 5, tariff='creator')
    assert q.profile == 'standard'
    assert q.cost == preset_manager.get_video_cost('seedance_2', 5)
    price_config['creator_tariff'] = {'enabled': True, 'video_models': {}}
    assert resolve_video_quote('seedance_2', 5, tariff='creator').profile == 'standard'
    assert resolve_video_quote('veo3', 5, tariff='creator').profile == 'standard'


def test_quote_is_immutable_and_captures_accepted_amount(price_config):
    from bot.creator_tariff import resolve_video_quote
    q = resolve_video_quote('seedance_2_5', 5, '720p', tariff='creator')
    snapshot = q.to_dict()
    price_config['creator_tariff']['video_models']['seedance_2_5']['quality_costs']['720p'] = 9
    assert q.cost == 10 and q.to_dict() == snapshot
    assert resolve_video_quote('seedance_2_5', 5, '720p', tariff='creator').cost == 45
    with pytest.raises(FrozenInstanceError):
        q.cost = 999


@pytest.mark.parametrize('value', [0, -1, True, float('nan'), float('inf'), '2', 0.00001, 1e307, 10**400])
def test_invalid_or_rounds_to_free_rates_are_rejected(price_config, value):
    from bot.creator_tariff import validate_creator_tariff_config
    raw = price_config['creator_tariff']
    raw['video_models']['seedance_2']['quality_costs']['720p'] = value
    with pytest.raises(ValueError):
        validate_creator_tariff_config(raw)


def test_incomplete_disabled_config_allowed_and_no_defaults_invented(price_config):
    from bot.creator_tariff import validate_creator_tariff_config
    assert validate_creator_tariff_config({'enabled': False, 'video_models': {}}) == {
        'enabled': False, 'video_models': {},
    }


def test_extra_configured_quality_is_preserved_and_required(price_config):
    from bot.creator_tariff import creator_tariff_status, validate_creator_tariff_config
    price_config['costs_reference']['video_models']['seedance_2_5']['quality_costs']['1080p'] = 13
    status = creator_tariff_status()
    assert '1080p' in status['required_qualities']['seedance_2_5']
    assert not status['configured']
    raw = price_config['creator_tariff']
    raw['video_models']['seedance_2_5']['quality_costs']['1080p'] = 3.0
    assert validate_creator_tariff_config(raw)['video_models']['seedance_2_5']['quality_costs']['1080p'] == 3


@pytest.mark.asyncio
async def test_actor_tariff_is_server_membership_and_admin_precedes_creator(price_config, monkeypatch):
    from unittest.mock import AsyncMock

    from bot import creator_tariff, creator_tariff_membership
    monkeypatch.setattr(config, 'is_admin', lambda uid: uid == 900)
    membership = AsyncMock(side_effect=lambda uid: uid == 901)
    monkeypatch.setattr(creator_tariff_membership, 'get_creator_tariff_membership', membership)
    assert await creator_tariff.get_actor_tariff(900) == 'admin'
    membership.assert_not_awaited()
    assert await creator_tariff.get_actor_tariff(901) == 'creator'
    assert await creator_tariff.get_actor_tariff(902) == 'standard'

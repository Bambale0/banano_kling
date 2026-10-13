"""Pure public pricing contract, without application/DB imports."""
import ast
import importlib.util
import json
import math
import sys
import types
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.prices = {'creator_tariff': {'enabled': True, 'video_models': {
            'seedance_2': {'quality_costs': {'720p': 1}},
            'seedance_2_5': {'quality_costs': {'480p': 2, '720p': 3}},
        }}, 'costs_reference': {'video_models': {}}}
        self.manager = types.SimpleNamespace(
            get_price_config=lambda: self.prices,
            normalize_video_model_key=lambda x: x,
            get_video_quality_costs=lambda model: {'720p': 8, '1080p': 9},
            _format_cost=lambda x: round(x * 2) / 2,
        )
        def capability(model):
            resolutions = {'seedance_2': ('720p',), 'seedance_2_5': ('480p', '720p')}.get(model, ('480P', '720P', '1080P'))
            return types.SimpleNamespace(resolutions=resolutions, durations=(5, 10))
        modules = {
            'bot.config': types.SimpleNamespace(config=types.SimpleNamespace(is_admin=lambda x: False)),
            'bot.model_capabilities': types.SimpleNamespace(get_video_capability=capability),
            'bot.services.preset_manager': types.SimpleNamespace(preset_manager=self.manager),
            'bot.video_reference_policy': types.SimpleNamespace(apply_video_reference_cost=lambda *x: 1),
        }
        spec = importlib.util.spec_from_file_location('creator_under_test', ROOT / 'bot/creator_tariff.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {**modules, 'creator_under_test': self.module}):
            spec.loader.exec_module(self.module)

    def test_legacy_seedance_stays_configured_and_new_models_fall_back(self):
        self.assertTrue(self.module.creator_tariff_status()['configured'])
        self.assertEqual(self.module.video_quality_rates('wan_3', tariff='creator')['720p'], 8)
        self.assertIn('wan_3', self.module.creator_tariff_status()['required_qualities'])

    def test_wan_admin_qualities_are_unique_canonical_keys(self):
        self.assertEqual(self.module.creator_tariff_status()['required_qualities']['wan_3'], ['480p', '720p', '1080p'])

    def test_wan_variants_have_independent_partial_rates(self):
        self.prices['creator_tariff']['video_models']['wan_3'] = {'quality_costs': {'720p': 2}}
        normalized = self.module.validate_creator_tariff_config(self.prices['creator_tariff'])
        self.assertEqual(normalized['video_models']['wan_3']['quality_costs'], {'720p': 2})
        self.assertEqual(self.module.video_quality_rates('wan_3', tariff='creator'), {'720p': 2, '1080p': 9})
        self.assertEqual(self.module.video_quality_rates('wan_3_prime', tariff='creator')['720p'], 8)

    def test_wan_rate_snapshot_is_actor_specific_and_quality_fallback(self):
        self.prices['creator_tariff']['video_models']['wan_3'] = {'quality_costs': {'720p': 2}}
        creator = self.module.video_rate_snapshot('wan_3', '720p', {'720p': 8}, tariff='creator')
        ordinary = self.module.video_rate_snapshot('wan_3', '720p', {'720p': 8})
        self.assertEqual(creator['rate'], 2)
        self.assertEqual(creator['profile'], 'creator')
        self.assertEqual(ordinary['rate'], 8)
        self.assertNotEqual(creator['revision'], ordinary['revision'])
        fallback = self.module.video_rate_snapshot('wan_3', '1080p', {'1080p': 9}, tariff='creator')
        self.assertEqual(fallback['profile'], 'standard')
        self.assertEqual(fallback['rate'], 9)

    def test_actual_wan_fixed_and_auto_quote_bill_effective_seconds_once(self):
        self.prices['creator_tariff']['video_models']['wan_3'] = {'quality_costs': {'720p': 2}}
        tree = ast.parse((ROOT / 'bot/services/wan3_prime_lifecycle.py').read_text())
        source = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Wan3PrimeLifecycle')
        selected = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in {'_rate_snapshot', '_quote_from_recipe'}]
        harness = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
        ns = {'math': math, 'uuid': uuid, '_json_dumps': lambda x: json.dumps(x, sort_keys=True), '_round_half_credit': lambda x: round(x * 2) / 2, 'Wan3PrimeQuote': lambda **x: types.SimpleNamespace(**x)}
        exec(compile(ast.fix_missing_locations(harness), '<actual-wan-quote>', 'exec'), ns)  # noqa: S102 - trusted pure source, no app imports
        lifecycle = types.SimpleNamespace(preset_manager=self.manager)
        lifecycle._rate_snapshot = types.MethodType(ns['_rate_snapshot'], lifecycle)
        recipe = types.SimpleNamespace(model='wan_3', resolution='720p', duration=5, input_video_seconds=7.5, prepared_input={}, fingerprint=lambda: 'recipe', safe_summary=lambda: {'model': 'wan_3'})
        actor = types.SimpleNamespace(is_admin=False)
        with patch.dict(sys.modules, {'bot.creator_tariff': self.module}):
            fixed = ns['_quote_from_recipe'](lifecycle, actor, recipe, tariff='creator')
            self.assertEqual(fixed.reserve_credits, 25)
            self.assertEqual(fixed.rate_per_second, 2)
            recipe.duration = -1
            auto = ns['_quote_from_recipe'](lifecycle, actor, recipe, tariff='creator')
            self.assertEqual(auto.reserve_credits, 60)
            self.assertEqual(auto.reserved_output_seconds, 22.5)

    def test_genjutsu_partial_rates_copy_and_fallback(self):
        self.prices['creator_tariff']['genjutsu'] = {'prices': {'restyle': {'720p': 3}}}
        ordinary = {'restyle': {'480p': 5, '720p': 8}, 'object_swap': {'720p': 12}}
        before = deepcopy(ordinary)
        snapshot = self.module.genjutsu_pricing_snapshot(ordinary, tariff='creator')
        self.assertEqual(snapshot['prices'], {'restyle': {'480p': 5, '720p': 3}, 'object_swap': {'720p': 12}})
        self.assertEqual(snapshot['profile'], 'creator')
        self.assertEqual(ordinary, before)
        self.assertEqual(self.module.genjutsu_price_rates(ordinary), before)

    def test_genjutsu_fractional_and_unknown_rates_rejected(self):
        for rates in ({'restyle': {'720p': 1.5}}, {'unknown': {'720p': 2}}, {'restyle': {'720p': True}}):
            self.prices['creator_tariff']['genjutsu'] = {'prices': rates}
            with self.assertRaises(ValueError):
                self.module.validate_creator_tariff_config(self.prices['creator_tariff'])


if __name__ == '__main__':
    unittest.main()

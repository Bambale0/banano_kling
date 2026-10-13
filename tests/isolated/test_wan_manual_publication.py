"""Pure contract tests, without importing the application or database."""
import ast
import unittest
from copy import deepcopy
from pathlib import Path


def load_function(path, name, namespace):
    tree = ast.parse(Path(path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), namespace)  # noqa: S102 - trusted repository AST
    return namespace[name]


class ManualPublicationTests(unittest.TestCase):
    def setUp(self):
        source = 'bot/services/wan3_prime_repeat.py'
        self.slots = load_function(source, 'source_slots', {'Any': object,
            'FRAME_FIELDS': ('first_frame_url', 'last_frame_url'),
            'ARRAY_FIELDS': {'reference_image_urls': 'image', 'reference_video_urls': 'video',
                             'reference_audio_urls': 'audio', 'reference_file_urls': 'file', 'reference_link_urls': 'link'}})
        fields = ('model', 'prompt', 'scenario', 'resolution', 'aspect_ratio', 'duration', 'audio', 'nsfw_checker',
                  'seed', 'first_frame_url', 'last_frame_url', 'reference_image_urls', 'reference_video_urls',
                  'reference_audio_urls', 'reference_file_urls', 'reference_link_urls')
        self.validate = load_function('bot/services/wan3_manual_publication.py', 'manual_publication_input',
            {'deepcopy': deepcopy, 'RECIPE_FIELDS': fields, 'source_slots': self.slots, 'Wan3PrimeValidationError': ValueError})
        self.recipe = {'model': 'wan_3', 'prompt': 'Image1 beside Image2', 'scenario': 'reference', 'resolution': '720P',
            'aspect_ratio': '9:16', 'duration': 5, 'audio': True, 'nsfw_checker': False,
            'reference_image_urls': ['https://owned.test/a.jpg', 'https://owned.test/b.jpg']}
        self.settings = {'model': 'wan_3', 'wan3_recipe': self.recipe, 'wan3_replacement_keys': ['image:0']}

    def test_both_models_preserve_order_and_explicit_replacements(self):
        for model in ('wan_3', 'wan_3_prime'):
            self.settings['model'] = self.recipe['model'] = model
            recipe, keys = self.validate(model, self.recipe['prompt'], self.settings)
            self.assertEqual(recipe, self.recipe)
            self.assertEqual(keys, ['image:0'])
            recipe['reference_image_urls'].clear()
            self.assertEqual(len(self.recipe['reference_image_urls']), 2)

    def test_whitespace_is_normalized_but_different_prompt_is_rejected(self):
        self.recipe['prompt'] = '  Image1 beside Image2  '
        recipe, _ = self.validate('wan_3', 'Image1 beside Image2', self.settings)
        self.assertEqual(recipe['prompt'], 'Image1 beside Image2')
        with self.assertRaises(ValueError):
            self.validate('wan_3', 'a different instruction', self.settings)

    def test_generic_legacy_payload_cannot_create_orphan(self):
        with self.assertRaises(ValueError):
            self.validate('wan_3', 'prompt', {'model': 'wan_3', 'scenario': 'imgtxt'})

    def test_rejects_model_mismatch_internal_fields_links_and_user_fields(self):
        for change in ({'model': 'wan_3_prime'}, {'source_feed_gen_id': 42}, {'trend_id': 42},
                       {'reference_link_urls': ['https://example.test']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate('wan_3', self.recipe['prompt'], {**self.settings, 'wan3_recipe': {**self.recipe, **change}})
        with self.assertRaises(ValueError):
            self.validate('wan_3', self.recipe['prompt'], {**self.settings, 'user_fields': [{'key': 'name'}]})

    def test_rejects_unknown_duplicate_missing_replacement_contract(self):
        for keys in (None, ['image:8'], ['image:0', 'image:0'], [1]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.validate('wan_3', self.recipe['prompt'], {**self.settings, 'wan3_replacement_keys': keys})


class PublicErrorsTests(unittest.TestCase):
    def test_status_never_passes_raw_remote_text_or_identity(self):
        clean = load_function('bot/services/wan3_public_errors.py', 'public_wan_status', {})
        source = {'status': 'unknown', 'error_message': 'ArbitraryCompany secret message',
                  'provider_model': 'private-model', 'provider_state': 'private-state', 'provider_task_id': 'private-id',
                  'task_id': 'owned-public-task', 'reserve_amount': 10}
        result = clean(source)
        self.assertNotIn('ArbitraryCompany', str(result))
        self.assertNotIn('private-', str(result))
        self.assertEqual(result['task_id'], 'owned-public-task')
        self.assertEqual(result['reserve_amount'], 10)


if __name__ == '__main__':
    unittest.main()

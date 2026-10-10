"""The filename boundary is pure; no application/DB startup is required."""
import ast
import re
from pathlib import Path

import pytest


def sanitizer():
    source = Path(__file__).parents[1] / 'bot/services/wan3_prime_storage.py'
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_safe_basename')
    namespace = {'Path': Path, 're': re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)  # noqa: S102 - trusted pure function, no application imports
    return namespace['_safe_basename']


@pytest.mark.parametrize(('name', 'expected'), [
    ('Фото.jpg', 'upload.jpg'), ('Видео.mov', 'upload.mov'), ('🌅.JPG', 'upload.jpg'),
    ('../Фото.PNG', 'upload.png'), ('C:\\fakepath\\Видео.MOV', 'upload.mov'),
    ('plain.mp4', 'plain.mp4'), ('photo.HEIC', 'photo.heic'), ('no_extension', 'no_extension'),
    ('foo.jpg ', 'upload'), ('a' * 140 + '.jpg', 'a' * 96 + '.jpg'),
])
def test_sanitizer_preserves_real_suffix_and_never_invents_allowed_one(name, expected):
    assert sanitizer()(name) == expected

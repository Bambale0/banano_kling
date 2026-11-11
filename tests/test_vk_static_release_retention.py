"""Regression: cached VK HTML must keep its hashed JS accessible on release rollover."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'retain_vk_immutable_assets.sh'


def test_old_vk_assets_remain_available_when_new_release_is_activated(tmp_path):
    previous = tmp_path / 'previous' / '_next' / 'static'
    staging = tmp_path / 'staging' / '_next' / 'static'
    (previous / 'chunks' / 'app').mkdir(parents=True)
    (staging / 'chunks' / 'app').mkdir(parents=True)
    (previous / 'chunks' / 'app' / 'page-old.js').write_text('window.old = true')
    (staging / 'chunks' / 'app' / 'page-new.js').write_text('window.new = true')
    (previous / 'chunks' / 'framework.js').write_text('shared-hash')
    (staging / 'chunks' / 'framework.js').write_text('shared-hash')
    for _ in range(2):
        subprocess.run(['bash', str(SCRIPT), str(previous), str(staging)], check=True)
    assert (staging / 'chunks' / 'app' / 'page-old.js').read_text() == 'window.old = true'
    assert (staging / 'chunks' / 'app' / 'page-new.js').read_text() == 'window.new = true'
    assert (staging / 'chunks' / 'framework.js').read_text() == 'shared-hash'


def test_immutable_asset_collision_fails_closed_without_overwrite(tmp_path):
    previous = tmp_path / 'previous'
    staging = tmp_path / 'staging'
    previous.mkdir()
    staging.mkdir()
    (previous / 'same.js').write_text('legacy')
    (staging / 'same.js').write_text('new')
    result = subprocess.run(['bash', str(SCRIPT), str(previous), str(staging)], capture_output=True, text=True, check=False)
    assert result.returncode == 4
    assert (staging / 'same.js').read_text() == 'new'


def test_missing_old_assets_is_valid_initial_deployment(tmp_path):
    new = tmp_path / 'new'
    new.mkdir()
    subprocess.run(['bash', str(SCRIPT), str(tmp_path / 'absent'), str(new)], check=True)

"""Filesystem regressions for runtime log retention and pytest isolation."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _isolated_env(**settings):
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(PROJECT_ROOT),
        "BOT_TOKEN": "123456:TEST_TOKEN_FOR_CI_ONLY",
        "BANANO_SKIP_PROJECT_ENV": "1",
        "BANANO_DISABLE_FILE_LOGGING": "0",
        "TZ": "Etc/GMT-3",
        **settings,
    }


def _copy_runtime_config(tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copyfile(PROJECT_ROOT / "data/price.json", tmp_path / "data/price.json")


@pytest.mark.parametrize("existing_log", [True, False])
def test_pytest_collection_never_writes_application_logs(tmp_path, existing_log):
    _copy_runtime_config(tmp_path)
    log_dir = tmp_path / "logs"
    if existing_log:
        log_dir.mkdir()
        (log_dir / "bot.log").write_text("production sentinel\n", encoding="utf-8")
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    shutil.copyfile(PROJECT_ROOT / "tests/conftest.py", test_dir / "conftest.py")
    (test_dir / "test_import_probe.py").write_text(
        "import logging\nimport bot.main\n"
        "logging.error('synthetic collection error must not enter application logs')\n"
        "def test_probe(): pass\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(test_dir)],
        cwd=tmp_path,
        env=_isolated_env(),
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    if existing_log:
        assert sorted(path.name for path in log_dir.iterdir()) == ["bot.log"]
        assert (log_dir / "bot.log").read_text(encoding="utf-8") == "production sentinel\n"
    else:
        assert not log_dir.exists()


@pytest.mark.parametrize(
    ("configured_days", "retained_days"),
    [(None, 7), ("4", 4), ("3", 3), ("0", 7), ("2", 7), ("bad", 7), ("3.5", 7)],
)
def test_rotation_and_cleanup_preserve_configured_history_in_utc(
    tmp_path, configured_days, retained_days
):
    _copy_runtime_config(tmp_path)
    env = _isolated_env()
    if configured_days is not None:
        env["BANANO_LOG_RETENTION_DAYS"] = configured_days
    script = textwrap.dedent(
        """
        import asyncio
        import json
        import logging
        import os
        from pathlib import Path
        import time
        from unittest.mock import patch

        time.tzset()
        start = 1767229200  # 2026-01-01 01:00:00 UTC; local clock is UTC+3.
        log_dir = Path('logs')
        log_dir.mkdir()
        active_log = log_dir / 'bot.log'
        active_log.touch()
        os.utime(active_log, (start, start))
        with patch('time.time', return_value=start):
            import bot.main as runtime

        # Each day's 22:00 UTC crosses local midnight but must not rotate yet.
        for day in range(11):
            timestamp = start + day * 86400
            with patch('time.time', return_value=timestamp):
                logging.getLogger('retention.probe').info('day-%02d', day)
            timestamp += 21 * 3600
            with patch('time.time', return_value=timestamp):
                logging.getLogger('retention.probe').info('late-%02d', day)
            os.utime(active_log, (timestamp, timestamp))

        with patch('time.time', return_value=timestamp):
            asyncio.run(runtime._remove_old_files(
                'logs', runtime.LOG_RETENTION_SECONDS,
                skip_filenames=runtime.ACTIVE_LOG_FILENAMES,
            ))
        logging.shutdown()
        print(json.dumps({
            'files': sorted(path.name for path in log_dir.iterdir()),
            'content': ''.join(path.read_text() for path in sorted(log_dir.iterdir())),
        }))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    expected_archives = [
        f"bot.log.2026-01-{day:02d}" for day in range(11 - retained_days, 11)
    ]
    assert report["files"] == ["bot.log", *expected_archives]
    for day in range(10 - retained_days, 11):
        assert f"day-{day:02d}" in report["content"]
    assert "2026-01-11 01:00:00" in report["content"]
    assert "2026-01-11 04:00:00" not in report["content"]

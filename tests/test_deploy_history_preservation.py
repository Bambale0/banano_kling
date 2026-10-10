"""Isolated shell contract tests: no Docker, app imports, or production paths."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts/deploy_backend_docker.sh"
MINIAPP = ROOT / "scripts/deploy_miniapp_local.sh"


def shell(script, cwd):
    return subprocess.run(
        ["bash", "-c", script], cwd=cwd, text=True, capture_output=True,
        env={"PATH": os.environ["PATH"], "PROJECT_DIR": str(cwd)}, timeout=10,
    )


def backend_harness():
    # Load definitions only. Every deploy side-effect seam is replaced below.
    source = BACKEND.read_text().rsplit('main "$@"', 1)[0]
    return source + """
require_root() { :; }
require_tools() { :; }
prepare_deploy_environment() { :; }
prepare_runtime_dirs() { :; }
require_disk_space() { :; }
build_or_pull_image() { :; }
backup_database() { echo BACKUP; }
service_exists() { return 1; }
compose() { printf 'COMPOSE %s\n' "$*"; }
wait_for_health() { echo HEALTH; }
verify_running_miniapp_url() { echo VERIFY_URL; }
backfill_public_feed_videos() { echo FEED_MAINTENANCE; }
reconcile_rendergrid_legacy_images() { echo IMAGE_MAINTENANCE; }
"""


class DeployHistoryPreservationTests(unittest.TestCase):
    def test_normal_backend_release_keeps_maintenance_separate(self):
        for opt_in in ("0", "1"):
            with self.subTest(opt_in=opt_in), tempfile.TemporaryDirectory() as tmp:
                result = shell(
                    backend_harness() +
                    f"ALLOW_MEDIA_MAINTENANCE={opt_in}; ACTION=deploy; main", tmp,
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("BACKUP", result.stdout)
            self.assertIn("HEALTH", result.stdout)
            self.assertIn("VERIFY_URL", result.stdout)
            self.assertNotIn("FEED_MAINTENANCE", result.stdout)
            self.assertNotIn("IMAGE_MAINTENANCE", result.stdout)

    def test_maintenance_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(backend_harness() + "ACTION=maintenance-media; main", tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ALLOW_MEDIA_MAINTENANCE=1", result.stderr)
        self.assertNotIn("MAINTENANCE", result.stdout)
        self.assertNotIn("BACKUP", result.stdout)

    def test_maintenance_runs_only_after_health_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(
                backend_harness() +
                "ALLOW_MEDIA_MAINTENANCE=1; ACTION=maintenance-media; main", tmp,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["HEALTH", "BACKUP", "FEED_MAINTENANCE", "IMAGE_MAINTENANCE"])

    def test_maintenance_cannot_skip_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(
                backend_harness() +
                "ALLOW_MEDIA_MAINTENANCE=1; SKIP_BACKUP=1; ACTION=maintenance-media; main", tmp,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("MAINTENANCE", result.stdout)

    def test_failed_health_blocks_maintenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(backend_harness() + """
wait_for_health() { return 1; }
ALLOW_MEDIA_MAINTENANCE=1
ACTION=maintenance-media
main
""", tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BACKUP", result.stdout)
        self.assertNotIn("MAINTENANCE", result.stdout)

    def test_failed_backup_blocks_maintenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(backend_harness() + """
backup_database() { return 1; }
ALLOW_MEDIA_MAINTENANCE=1
ACTION=maintenance-media
main
""", tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("MAINTENANCE", result.stdout)

    def test_failed_deploy_health_preserves_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(backend_harness() + """
service_exists() { return 0; }
systemctl() { :; }
wait_for_health() { return 1; }
rollback_to_systemd() { echo ROLLBACK; }
ACTION=deploy
main
""", tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BACKUP", result.stdout)
        self.assertIn("ROLLBACK", result.stdout)
        self.assertNotIn("MAINTENANCE", result.stdout)

    def test_backup_runs_use_unique_directories_and_preserve_history(self):
        source = BACKEND.read_text().rsplit('main "$@"', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            helper = scripts / "backup_db.sh"
            helper.write_text(
                '#!/bin/bash\n'
                'test "$SEND_BACKUP_TO_ADMINS" = 0 || exit 1\n'
                'printf fresh > "$DB_BACKUP_DIR/postgres-latest.dump"\n'
            )
            helper.chmod(0o700)
            backups = root / "backups"
            backups.mkdir()
            previous = backups / "postgres-latest.dump"
            previous.write_text("historical")
            result = shell(source + """
require_disk_space() { :; }
backup_database
backup_database
""", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(previous.read_text(), "historical")
            runs = list(backups.glob("predeploy-*"))
            self.assertEqual(len(runs), 2)
            for run in runs:
                self.assertEqual((run / "postgres-latest.dump").read_text(), "fresh")
                self.assertIn(str(run), result.stdout)

    def test_disk_preflight_fails_closed_without_mutation(self):
        source = BACKEND.read_text().rsplit('main "$@"', 1)[0]
        for available in ("0", "invalid"):
            with self.subTest(available=available), tempfile.TemporaryDirectory() as tmp:
                result = shell(source + """
df() { printf 'Filesystem 1B-blocks Used Available Use%% Mounted\\nfs 99 99 """ + available + """ 100%% /\\n'; }
require_disk_space "$PROJECT_DIR"
echo SHOULD_NOT_RUN
""", tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SHOULD_NOT_RUN", result.stdout)

    def test_deploy_checks_disk_before_build_or_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = shell(backend_harness() + """
require_disk_space() { echo DISK_FULL; return 1; }
build_or_pull_image() { echo BUILD; }
ACTION=deploy
main
""", tmp)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BUILD", result.stdout)
        self.assertNotIn("BACKUP", result.stdout)
        self.assertNotIn("MAINTENANCE", result.stdout)

    def test_maintenance_command_failures_are_reported(self):
        source = BACKEND.read_text().rsplit('main "$@"', 1)[0]
        for function in ("backfill_public_feed_videos", "reconcile_rendergrid_legacy_images"):
            with self.subTest(function=function), tempfile.TemporaryDirectory() as tmp:
                result = shell(source + """
compose() { return 1; }
""" + function, tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("maintenance failed", result.stderr)

    def test_miniapp_disk_preflight_precedes_build(self):
        text = MINIAPP.read_text()
        build = text.index("npm ci --no-audit")
        self.assertLess(text.index('require_disk_space "$PROJECT_DIR"'), build)
        self.assertLess(text.index('require_disk_space "$BACKUP_ROOT"'), build)

    def test_miniapp_exact_revision_and_asset_checks_remain(self):
        text = MINIAPP.read_text()
        for check in (
            '[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]]',
            '[[ "$live_revision" == "$EXPECTED_SHA" ]]',
            '[[ -s "${OUT_DIR}/index.html" ]]',
            '[[ -d "${OUT_DIR}/_next/static" ]]',
            '[[ -s "$work/assets.txt" ]]',
            'npm run lint',
        ):
            self.assertIn(check, text)

    def test_miniapp_backup_creation_retains_every_previous_backup(self):
        text = MINIAPP.read_text()
        start = text.index('if [[ -f "${MINIAPP_ROOT}/index.html" ]]')
        end = text.index('log "Publishing static export', start)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "live"
            backups = root / "backups"
            live.mkdir()
            backups.mkdir()
            (live / "index.html").write_text("current")
            (live / "revision.txt").write_text("old-sha\n")
            for i in range(10):
                old = backups / f"old-{i}"
                old.mkdir()
                (old / "index.html").write_text(f"history {i}")
            script = """set -Eeuo pipefail
IFS=$'\n\t'
MINIAPP_ROOT="$PROJECT_DIR/live"
BACKUP_ROOT="$PROJECT_DIR/backups"
KEEP_BACKUPS=1
log() { :; }
""" + text[start:end]
            result = shell(script, tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            for i in range(10):
                self.assertEqual((backups / f"old-{i}" / "index.html").read_text(), f"history {i}")
            created = [p for p in backups.iterdir() if not p.name.startswith("old-")]
            self.assertEqual(len(created), 1)
            self.assertEqual((created[0] / "index.html").read_text(), "current")
            revision_start = text.index('revision_file="$(mktemp')
            revision_end = text.index('chown -R root:root', revision_start)
            result = shell(
                'set -Eeuo pipefail; MINIAPP_ROOT="$PROJECT_DIR/live"; EXPECTED_SHA=new-sha\n'
                + text[revision_start:revision_end], tmp,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((live / "revision.txt").read_text(), "new-sha\n")
            self.assertEqual((created[0] / "revision.txt").read_text(), "old-sha\n")


if __name__ == "__main__":
    unittest.main()

"""Release-safety regression tests for admin-managed runtime pricing."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_both_production_paths_preserve_runtime_price_by_default():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    preserve_guard = (
        'if [ "$preserve_runtime_price" = true ] && [ -f "$RUNTIME_PRICE_FILE" ]; then'
    )
    dirty_only_guard = (
        'if printf \'%s\\n\' "$dirty_paths" | grep -qxF "$RUNTIME_PRICE_FILE"; then'
    )

    assert workflow.count(preserve_guard) == 2
    assert dirty_only_guard not in workflow
    assert workflow.count('cp -- "$RUNTIME_PRICE_FILE" "$runtime_price_backup"') == 2
    assert workflow.count('cp -- "$runtime_price_backup" "$RUNTIME_PRICE_FILE"') == 2


def test_versioned_price_change_is_applied_instead_of_preserved():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    change_guard = (
        'if ! git diff --quiet HEAD "$EXPECTED_SHA" -- "$RUNTIME_PRICE_FILE"; then'
    )

    assert workflow.count(change_guard) == 2
    assert workflow.count("preserve_runtime_price=false") == 2
    assert workflow.count('echo "Applying versioned pricing from $RUNTIME_PRICE_FILE"') == 2


def test_runtime_price_is_restored_after_exact_sha_reset():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    reset_marker = 'git reset --hard "$EXPECTED_SHA"'
    restore_marker = 'cp -- "$runtime_price_backup" "$RUNTIME_PRICE_FILE"'

    assert workflow.count(reset_marker) == 2
    assert workflow.count(restore_marker) == 2

    first_reset = workflow.index(reset_marker)
    first_restore = workflow.index(restore_marker, first_reset)
    second_reset = workflow.index(reset_marker, first_reset + len(reset_marker))
    second_restore = workflow.index(restore_marker, second_reset)

    assert first_restore > first_reset
    assert second_restore > second_reset


def test_test_only_server_drift_does_not_block_exact_sha_deploy():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("grep -vE '^tests/'") == 2
    assert workflow.count(
        'echo "Tracked runtime changes outside $RUNTIME_PRICE_FILE block automatic deployment:"'
    ) == 2

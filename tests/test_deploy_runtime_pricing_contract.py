def _source() -> str:
    with open(".github/workflows/deploy-production.yml", encoding="utf-8") as workflow:
        return workflow.read()


def test_production_deploy_preserves_runtime_price_and_blocks_runtime_drift() -> None:
    source = _source()

    # Both deployment paths (SSH and the nuromix fallback) must preserve the
    # admin-managed runtime tariff file across the exact-SHA git reset.
    assert source.count('RUNTIME_PRICE_FILE="data/price.json"') == 2
    assert source.count('echo "Preserving runtime pricing from $RUNTIME_PRICE_FILE"') == 2
    assert source.count('echo "Restored runtime pricing to $RUNTIME_PRICE_FILE"') == 2

    # Staged edits are never accepted. Unstaged runtime/config/code edits still
    # abort deployment, while test-only drift may be discarded by exact-SHA reset.
    assert source.count("if ! git diff --cached --quiet; then") == 2
    assert source.count('grep -vxF "$RUNTIME_PRICE_FILE"') == 2
    assert source.count("grep -vE '^tests/'") == 2
    assert source.count(
        'Tracked runtime changes outside $RUNTIME_PRICE_FILE block automatic deployment:'
    ) == 2


def test_runtime_price_is_restored_after_exact_sha_reset() -> None:
    source = _source()

    reset_marker = 'git reset --hard "$EXPECTED_SHA"'
    restore_marker = 'cp -- "$runtime_price_backup" "$RUNTIME_PRICE_FILE"'

    # Verify ordering independently inside both deploy scripts.
    first_reset = source.index(reset_marker)
    first_restore = source.index(restore_marker, first_reset)
    second_reset = source.index(reset_marker, first_restore)
    second_restore = source.index(restore_marker, second_reset)

    assert first_reset < first_restore < second_reset < second_restore

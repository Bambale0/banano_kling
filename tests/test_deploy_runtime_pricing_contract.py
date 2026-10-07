def _source() -> str:
    with open(".github/workflows/deploy-production.yml", encoding="utf-8") as workflow:
        return workflow.read()


def test_production_deploy_preserves_runtime_price_and_blocks_runtime_drift() -> None:
    source = _source()

    # Both deployment paths (SSH and the nuromix fallback) must preserve the
    # admin-managed runtime tariff file without ever rewriting it.
    assert source.count('RUNTIME_PRICE_FILE="data/price.json"') == 2
    assert source.count('echo "Preserving runtime pricing from $RUNTIME_PRICE_FILE"') == 2
    assert source.count('echo "Retained runtime pricing at $RUNTIME_PRICE_FILE"') == 2

    # Staged edits are never accepted. Unstaged runtime/config/code edits still
    # abort deployment, while test-only drift may be discarded by exact-SHA reset.
    assert source.count("if ! git diff --cached --quiet; then") == 2
    assert source.count('grep -vxF "$RUNTIME_PRICE_FILE"') == 2
    assert source.count("grep -vE '^tests/'") == 2
    assert source.count(
        'Tracked runtime changes outside $RUNTIME_PRICE_FILE block automatic deployment:'
    ) == 2


def test_standard_checkout_excludes_runtime_price_from_worktree_writes() -> None:
    source = _source()

    assert source.count(
        'git restore --source="$EXPECTED_SHA" --worktree -- . ":(top,exclude)$RUNTIME_PRICE_FILE"'
    ) == 2
    assert source.count('git reset --mixed --no-refresh "$EXPECTED_SHA"') == 2
    assert 'git reset --hard "$EXPECTED_SHA"' not in source
    assert 'git switch tanyapi' not in source
    assert 'cp -- "$runtime_price_backup" "$RUNTIME_PRICE_FILE"' not in source
    assert source.count('ln -T -- "$runtime_price_default" "$RUNTIME_PRICE_FILE"') == 2

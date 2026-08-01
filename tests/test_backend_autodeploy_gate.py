from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy-production.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_autodeploy_runs_for_tanyapi_and_exact_sha() -> None:
    text = _workflow_text()

    assert "branches: [tanyapi]" in text
    assert 'git reset --hard "$EXPECTED_SHA"' in text
    assert 'revision" = "$EXPECTED_SHA"' in text
    assert "Production deployment gate" in text


def test_autodeploy_requires_verified_ci_job_steps() -> None:
    text = _workflow_text()

    assert 'actions/runs/${run_id}/jobs' in text
    assert "GitHub runner — Production Docker image" in text
    assert "Build image with GitHub Actions cache" in text
    assert "Verify image filesystem and Python imports" in text
    assert "Publish verified image" in text
    assert "nuromix fallback — Full CI validation" in text
    assert "Run full safe regression suite" in text
    assert "Publish nuromix-verified image" in text
    assert "CI completed without a fully verified image path" in text


def test_autodeploy_does_not_trust_only_workflow_conclusion() -> None:
    text = _workflow_text()

    assert "Matching CI passed for $GITHUB_SHA" not in text
    assert '[ "$conclusion" = success ]' not in text

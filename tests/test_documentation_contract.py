"""Guard current operator docs from regressing to old release or repeat policies."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = [
    "AGENTS.md", "README.md", "docs/README.md", "docs/PUBLICATION_REPEAT_CONTRACT.md",
    "docs/PRIVATE_REPEAT_REFERENCES.md", "docs/VIDEO_REPEAT_PROMPT_CONTRACT.md",
    "docs/generation-privacy.md", "docs/production_auto_deploy.md",
    "docs/development-deployment.md", "docs/production-deployment.md",
    "docs/runbook.md", "docs/troubleshooting.md",
    "docs/architecture.md", "docs/wan3-prime-integration.md",
    "docs/TREND_SHOWCASE_CATEGORIES.md", "docs/DOCUMENTATION_INDEX.md",
    "docs/POST_RELEASE_AUDIT_2026-10-16.md", "frontend/miniapp-v0/README.md",
]


def test_current_release_policy_not_old_dev_promotion():
    for rel in ("AGENTS.md", "README.md", "docs/README.md", "docs/production_auto_deploy.md"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "tanyapi" in text, rel
        assert "pull request dev -> tanyapi" not in text, rel
        assert "pr dev -> tanyapi" not in text, rel
        assert "pr в dev ->" not in text, rel
    runbook = (ROOT / "docs/runbook.md").read_text(encoding="utf-8")
    assert "docker inspect" in runbook
    assert "revision.txt" in runbook


def test_published_derivatives_are_repeatable_without_ancestor_redirect():
    contract = (ROOT / "docs/PUBLICATION_REPEAT_CONTRACT.md").read_text()
    guidance = (ROOT / "AGENTS.md").read_text()
    assert "source_feed_gen_id" in contract
    assert "repeat" in contract and "remix" in contract and "trend" in contract
    assert "An independently published completed generation is repeatable" in guidance
    assert "ancestry-only" in guidance
    assert "private_repeat_permission_source_id" in (
        ROOT / "docs/PRIVATE_REPEAT_REFERENCES.md"
    ).read_text()


def test_active_docs_links_and_fences_are_complete():
    for rel in ACTIVE:
        file = ROOT / rel
        content = file.read_text(encoding="utf-8")
        assert sum(line.lstrip().startswith(chr(96) * 3) for line in content.splitlines()) % 2 == 0, rel
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if target.startswith(("https://", "http://", "mailto:", "tel:", "#")):
                continue
            local = target.split("#")[0].split("?")[0].replace("%20", " ")
            if local and not local.startswith("/"):
                assert (file.parent / local).exists(), (rel, local)


def test_doc_index_covers_all_project_markdown_without_vendor_skills():
    manifest = (ROOT / "docs/DOCUMENTATION_INDEX.md").read_text()
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "*.md"], text=True
    ).splitlines()
    required = {
        item for item in tracked
        if not item.startswith(".agents/skills/") and item != "docs/DOCUMENTATION_INDEX.md"
    }
    listed = set(re.findall(r"^\- \[([^]]+\.md)\]\([^)]+\)", manifest, re.MULTILINE))
    assert listed == required

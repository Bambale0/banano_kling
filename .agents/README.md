# .agents — global Agent Skills library

This repository is the global skills home for AI agents. It is meant to be used across **all projects**, not as a one-off prompt collection.

The repository itself is intended to be checked out as `~/.agents`, so the installable skills live at the repository root under `skills/`. That produces the cross-client path:

```text
~/.agents/
├── AGENTS.md
├── SKILL.md
├── SKILLS_INDEX.md
├── skills/
│   ├── <skill-name>/
│   │   ├── SKILL.md
│   │   ├── scripts/       # optional
│   │   ├── references/    # optional
│   │   └── assets/        # optional
│   └── ...
└── scripts/
```

This follows the Agent Skills open format and the widely adopted `.agents/skills/` discovery convention. A project-local checkout at `<project>/.agents/skills/` and a user-global checkout at `~/.agents/skills/` can therefore share the same skill payload.

## Rule for agents

**Use this skill library in every project.** That does **not** mean loading every skill on every task. Agents must use progressive disclosure:

1. Read the project instructions (`AGENTS.md`, README, docs) first.
2. Discover relevant skills by `name` and `description`.
3. Activate only the smallest set that matches the task.
4. Read the selected skill's full `SKILL.md`.
5. Load `references/`, `scripts/`, and `assets/` only when the selected skill calls for them.
6. Follow project-specific instructions and user requirements over generic skill advice when they conflict.
7. Verify the result and report which skills materially influenced the work.

The complete operating rules and skill map are in [`AGENTS.md`](AGENTS.md). The generated exhaustive catalog is in [`SKILLS_INDEX.md`](SKILLS_INDEX.md).

## Install globally

Clone this private repository as your global `.agents` directory:

```bash
git clone git@github.com:Bambale0/.agents.git ~/.agents
```

Update later with:

```bash
git -C ~/.agents pull --ff-only
```

For a client that only scans project-local skills, link the global library into the project:

```bash
mkdir -p .agents
ln -s "$HOME/.agents/skills" .agents/skills
```

Or use the helper:

```bash
bash ~/.agents/scripts/install-project.sh /path/to/project
```

## Skill routing

Two bootstrap files make the catalog easier to use:

- [`SKILL.md`](SKILL.md) — root bootstrap/router instructions for agents that inspect this repository directly.
- [`skills/agents-global-router/SKILL.md`](skills/agents-global-router/SKILL.md) — the spec-compliant discoverable router skill.

Do not treat the root `SKILL.md` as an installable skill by itself; the canonical discoverable copy is under `skills/agents-global-router/` so its `name` matches its directory as required by the Agent Skills specification.

## Sources

The mirrored catalog is pinned for reproducibility in [`sources.lock.json`](sources.lock.json):

- **Agentic Awesome Skills v17.3.0** — canonical `skills/` tree only. Plugin/bundle copies are intentionally not duplicated.
- **OpenAI `skills` snapshot** at commit `778b0e6129cf18cbaee3bf11479f583fadae8d03` — curated and system skills from the user-supplied archive. The upstream repository is deprecated; this snapshot is retained because the skills themselves remain useful.
- **Local custom skills** — maintained directly in this repository, including `frontend-ux-audit`.

When skill names collide, no skill is silently discarded:

- the OpenAI system skill keeps the canonical short name;
- the OpenAI curated alternative is preserved with `-curated`;
- a community alternative is preserved with `-community`.

One legacy community skill named `android_ui_verification` is normalized to `android-ui-verification` so the directory and frontmatter satisfy the open specification.

Font binary assets are not mirrored. No skill directory is dropped because of this; instructions, scripts, references, and non-font assets are retained.

## Sync and validation

The workflow [`.github/workflows/sync-skills.yml`](.github/workflows/sync-skills.yml) rebuilds the managed catalog from the pinned sources, generates indexes, validates all skill manifests against the official `agentskills/agentskills` reference validator, and commits the generated catalog back to `main`.

Run the sync locally from cloned source checkouts with:

```bash
python -m pip install pyyaml
python scripts/sync_skills.py \
  --community-dir /tmp/agentic-awesome-skills \
  --openai-dir /tmp/openai-skills
```

Then validate:

```bash
python -m pip install \
  'skills-ref @ git+https://github.com/agentskills/agentskills.git@69ef37e9424c0a7ea9dd2293b559e43ec8176379#subdirectory=skills-ref'
python scripts/validate_skills.py
```

## Security and execution

Skills are instructions and may include executable scripts. A skill being present in this repository is **not** permission to run arbitrary commands. Before executing bundled code, agents must inspect the relevant skill, honor the user's intent and tool permissions, and avoid leaking secrets or making destructive changes without explicit authorization.

## References

- Agent Skills: https://agentskills.io/
- Specification: https://agentskills.io/specification
- Reference implementation: https://github.com/agentskills/agentskills
- Community catalog source: https://github.com/sickn33/agentic-awesome-skills
- OpenAI historical skills source: https://github.com/openai/skills

# Индекс документации проекта NEUROMIX

Обновлён 2026-10-16. Этот индекс включает все отслеживаемые `*.md` проекта вне внешней библиотеки `.agents/skills/*`. Наличие файла в списке **не означает**, что его содержимое является текущей настройкой production.

**Правило доверия:** `AGENTS.md` → [PUBLICATION_REPEAT_CONTRACT.md](PUBLICATION_REPEAT_CONTRACT.md) → действующие тематические контракты → код/тесты текущей ветки и проверенный production. Исторические отчёты и provider snapshots не служат источником текущих веток, endpoint или авторизации.

- **Действующие документы:** разделы 01–03, с учётом явно помеченных legacy-подразделов.
- **Reference:** раздел 04 — снимки API/примеров, которые нужно сверять с настоящим адаптером; никогда не считать автоматически включённым модель только из-за наличия справочника.
- **История:** раздел 05 — фиксирует состояние на дату записи, старые ошибочные решения остаются только как аудит, окончательное правило см. раздел 01.
- **Агентские/QA правила:** раздел 06 — совместимы с корневым `AGENTS.md`; его приоритет выше.

Текущие нарушения и незавершённые проверки: [POST_RELEASE_AUDIT_2026-10-16.md](POST_RELEASE_AUDIT_2026-10-16.md).

## 01. Обязательные правила и продуктовые контракты (11)

- [AGENTS.md](../AGENTS.md)
- [README.md](../README.md)
- [docs/FEED_SHARE_ATTRIBUTION.md](FEED_SHARE_ATTRIBUTION.md)
- [docs/GENJUTSU_FEED.md](GENJUTSU_FEED.md)
- [docs/PRIVATE_REPEAT_REFERENCES.md](PRIVATE_REPEAT_REFERENCES.md)
- [docs/PUBLICATION_REPEAT_CONTRACT.md](PUBLICATION_REPEAT_CONTRACT.md)
- [docs/README.md](README.md)
- [docs/SEEDANCE25_IDENTITY_TRANSFER.md](SEEDANCE25_IDENTITY_TRANSFER.md)
- [docs/TREND_SHOWCASE_CATEGORIES.md](TREND_SHOWCASE_CATEGORIES.md)
- [docs/VIDEO_REPEAT_PROMPT_CONTRACT.md](VIDEO_REPEAT_PROMPT_CONTRACT.md)
- [docs/generation-privacy.md](generation-privacy.md)

## 02. Действующая эксплуатация и развёртывание (18)

- [docs/development-deployment.md](development-deployment.md) — только явно помеченный legacy/optional процесс
- [docs/docker_backend.md](docker_backend.md)
- [docs/environment.md](environment.md)
- [docs/frontend_auto_deploy.md](frontend_auto_deploy.md)
- [docs/frontend_autodeploy_exact_sha.md](frontend_autodeploy_exact_sha.md)
- [docs/migration.md](migration.md)
- [docs/miniapp-frontend-auto-install.md](miniapp-frontend-auto-install.md)
- [docs/miniapp-frontend-deployment.md](miniapp-frontend-deployment.md) — только явно помеченный legacy/optional процесс
- [docs/nuromix_runner.md](nuromix_runner.md)
- [docs/operations/memory-diagnostics.md](operations/memory-diagnostics.md)
- [docs/postgres-migration.md](postgres-migration.md)
- [docs/production-deployment.md](production-deployment.md)
- [docs/production_auto_deploy.md](production_auto_deploy.md)
- [docs/runbook.md](runbook.md)
- [docs/troubleshooting.md](troubleshooting.md)
- [docs/zero-downtime-migration.md](zero-downtime-migration.md)
- [frontend/miniapp-v0/README.md](../frontend/miniapp-v0/README.md)
- [ops/media/README.md](../ops/media/README.md)

## 03. Архитектура, функции и администрирование (37)

- [docs/CREATOR_TARIFF.md](CREATOR_TARIFF.md)
- [docs/PARTNER_POLICY.md](PARTNER_POLICY.md)
- [docs/REFERRAL_NOTIFICATIONS.md](REFERRAL_NOTIFICATIONS.md)
- [docs/TREND_USER_VARIABLES.md](TREND_USER_VARIABLES.md)
- [docs/admin-trends-guide.md](admin-trends-guide.md)
- [docs/architecture.md](architecture.md)
- [docs/bot_feed_agent_instructions.md](bot_feed_agent_instructions.md)
- [docs/branding.md](branding.md)
- [docs/cdn-manager.md](cdn-manager.md)
- [docs/codex-admin-porting-instruction.md](codex-admin-porting-instruction.md)
- [docs/deployment-retrigger-log.md](deployment-retrigger-log.md)
- [docs/gemini-3-pro-image-admin-test.md](gemini-3-pro-image-admin-test.md)
- [docs/gpt-image-2-5-admin-test.md](gpt-image-2-5-admin-test.md)
- [docs/internal-admin-api.md](internal-admin-api.md)
- [docs/internal-admin-cms-support.md](internal-admin-cms-support.md)
- [docs/internal-admin-notifications.md](internal-admin-notifications.md)
- [docs/internal-admin-operations.md](internal-admin-operations.md)
- [docs/internal-admin-payments-tariffs.md](internal-admin-payments-tariffs.md)
- [docs/internal-admin-user-commands.md](internal-admin-user-commands.md)
- [docs/pinterest-trend-flow.md](pinterest-trend-flow.md)
- [docs/prompt_guide.md](prompt_guide.md)
- [docs/reference-system.md](reference-system.md)
- [docs/rendergrid-nanobanana-provider.md](rendergrid-nanobanana-provider.md)
- [docs/repeat-result-regression.md](repeat-result-regression.md)
- [docs/research/higgsfield-genjutsu-api.md](research/higgsfield-genjutsu-api.md)
- [docs/roadmap.md](roadmap.md)
- [docs/run_guide.md](run_guide.md)
- [docs/test.md](test.md)
- [docs/tracemap.md](tracemap.md)
- [docs/ux_analysis.md](ux_analysis.md)
- [docs/vk_bot_architecture.md](vk_bot_architecture.md)
- [static/ofert.md](../static/ofert.md)
- [tracemap_complete_RU.md](../tracemap_complete_RU.md)
- [tracemap_credits_check.md](../tracemap_credits_check.md)
- [tracemap_feed_referral.md](../tracemap_feed_referral.md)
- [tracemap_generation.md](../tracemap_generation.md)
- [tracemap_payments.md](../tracemap_payments.md)

## 04. Интеграции и технические reference (21)

- [docs/README_gemini_image_generation.md](README_gemini_image_generation.md)
- [docs/banana_api.md](banana_api.md)
- [docs/crypto_api.md](crypto_api.md)
- [docs/freekassa.md](freekassa.md)
- [docs/gemini-photo-instructions.md](gemini-photo-instructions.md)
- [docs/integrations/genjutsu/README.md](integrations/genjutsu/README.md) — provider/reference snapshot, сверять с runtime
- [docs/integrations/genjutsu/terminal-notifications.md](integrations/genjutsu/terminal-notifications.md) — provider/reference snapshot, сверять с runtime
- [docs/kie_ai_integration.md](kie_ai_integration.md)
- [docs/kling_api.md](kling_api.md)
- [docs/kling_api_v2.md](kling_api_v2.md)
- [docs/lava_legacy_reconcile.md](lava_legacy_reconcile.md)
- [docs/lava_payment_reliability.md](lava_payment_reliability.md)
- [docs/motion_control_api.md](motion_control_api.md)
- [docs/nginx_lava.md](nginx_lava.md) — только явно помеченный legacy/optional процесс
- [docs/prodamus-payform.md](prodamus-payform.md)
- [docs/prompt-analyzer.md](prompt-analyzer.md)
- [docs/providers/wan3-prime-kie.md](providers/wan3-prime-kie.md) — provider/reference snapshot, сверять с runtime
- [docs/robokassa.md](robokassa.md)
- [docs/tbank_api.md](tbank_api.md)
- [docs/veo_api.md](veo_api.md)
- [docs/wan3-prime-integration.md](wan3-prime-integration.md)

## 05. Исторические отчёты, snapshots и журналы (18)

- [QA_AUDIT_CHECKLIST.md](../QA_AUDIT_CHECKLIST.md)
- [audit_report.md](../audit_report.md)
- [docs/POST_RELEASE_AUDIT_2026-10-16.md](POST_RELEASE_AUDIT_2026-10-16.md) — наблюдения и открытые риски по состоянию релиза
- [docs/admin-contour-audit-2026-08-13.md](admin-contour-audit-2026-08-13.md)
- [docs/agents/ADMIN_MODEL_COVERAGE_20261008.md](agents/ADMIN_MODEL_COVERAGE_20261008.md) — журнал/история; решения могли быть заменены
- [docs/agents/BANANA_ADMIN_GUARD_20261008.md](agents/BANANA_ADMIN_GUARD_20261008.md) — журнал/история; решения могли быть заменены
- [docs/agents/CREATOR_WAN_GENJUTSU.md](agents/CREATOR_WAN_GENJUTSU.md) — журнал/история; решения могли быть заменены
- [docs/agents/EXECUTION.md](agents/EXECUTION.md) — журнал/история; решения могли быть заменены
- [docs/agents/GENJUTSU_FEED_UI.md](agents/GENJUTSU_FEED_UI.md) — журнал/история; решения могли быть заменены
- [docs/agents/PROJECT_DEBUG_72H_2026-10-01.md](agents/PROJECT_DEBUG_72H_2026-10-01.md) — журнал/история; решения могли быть заменены
- [docs/agents/REFERRAL_NOTIFICATIONS_20261009.md](agents/REFERRAL_NOTIFICATIONS_20261009.md) — журнал/история; решения могли быть заменены
- [docs/agents/WAN3_PRIME_20261009.md](agents/WAN3_PRIME_20261009.md) — журнал/история; решения могли быть заменены
- [docs/agents/WAN_CHUNK_TRANSPORT_2026-10-13.md](agents/WAN_CHUNK_TRANSPORT_2026-10-13.md) — журнал/история; решения могли быть заменены
- [docs/agents/WAN_PUBLIC_REPEAT_HOTFIX.md](agents/WAN_PUBLIC_REPEAT_HOTFIX.md) — журнал/история; решения могли быть заменены
- [docs/agents/WAN_TREND_PUBLICATION_2026-10-13.md](agents/WAN_TREND_PUBLICATION_2026-10-13.md) — журнал/история; решения могли быть заменены
- [docs/miniapp-audit-and-codex-porting-instruction-2026-08-21.md](miniapp-audit-and-codex-porting-instruction-2026-08-21.md)
- [frontend/miniapp-v0/DEPLOY_TRIGGER_2026-08-04.md](../frontend/miniapp-v0/DEPLOY_TRIGGER_2026-08-04.md)
- [memory/2026-07-05.md](../memory/2026-07-05.md)

## 06. Инструкции агентов, QA и вспомогательные документы (27)

- [.agents/README.md](../.agents/README.md)
- [.github/agents/00-architect.md](../.github/agents/00-architect.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/01-backend-python.md](../.github/agents/01-backend-python.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/02-frontend-react.md](../.github/agents/02-frontend-react.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/03-telegram-bot.md](../.github/agents/03-telegram-bot.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/04-api-integrator.md](../.github/agents/04-api-integrator.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/05-database.md](../.github/agents/05-database.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/06-test-qa.md](../.github/agents/06-test-qa.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/07-security-reviewer.md](../.github/agents/07-security-reviewer.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/08-devops.md](../.github/agents/08-devops.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/09-code-reviewer.md](../.github/agents/09-code-reviewer.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/10-docs.md](../.github/agents/10-docs.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/11-release-manager.md](../.github/agents/11-release-manager.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/12-debugger.md](../.github/agents/12-debugger.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/agents/13-performance.md](../.github/agents/13-performance.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/copilot-instructions.md](../.github/copilot-instructions.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/instructions/frontend.instructions.md](../.github/instructions/frontend.instructions.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/instructions/python-backend.instructions.md](../.github/instructions/python-backend.instructions.md) — инструкции агента/процесса, ниже AGENTS.md
- [.github/instructions/tests.instructions.md](../.github/instructions/tests.instructions.md) — инструкции агента/процесса, ниже AGENTS.md
- [FSM_USER_FLOWS.md](../FSM_USER_FLOWS.md)
- [KATYA_SUPERVISOR.md](../KATYA_SUPERVISOR.md)
- [OPENCLAW_BRIEF.md](../OPENCLAW_BRIEF.md)
- [guide.md](../guide.md)
- [llms.md](../llms.md)
- [prompts/issue-template-agent-task.md](../prompts/issue-template-agent-task.md)
- [prompts/pr-review-checklist.md](../prompts/pr-review-checklist.md)
- [prompts/sprint-orchestrator-prompt.md](../prompts/sprint-orchestrator-prompt.md)

**Всего:** 132 отслеживаемых/добавленных Markdown-документов вне внешней skill-библиотеки. Не учитываются generated assets и содержимое чужих `.agents/skills/*`.

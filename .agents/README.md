# Development Agents Pack

Готовый набор агентских профилей и общих инструкций для GitHub Copilot custom agents, Codex/OpenClaw-style agents и любых агентных раннеров, которые читают Markdown-инструкции.

## Куда положить файлы

```text
repo/
  AGENTS.md
  .github/
    copilot-instructions.md
    instructions/
      python-backend.instructions.md
      frontend.instructions.md
      tests.instructions.md
    agents/
      00-architect.md
      01-backend-python.md
      02-frontend-react.md
      03-telegram-bot.md
      04-api-integrator.md
      05-database.md
      06-test-qa.md
      07-security-reviewer.md
      08-devops.md
      09-code-reviewer.md
      10-docs.md
      11-release-manager.md
      12-debugger.md
      13-performance.md
  prompts/
    issue-template-agent-task.md
    pr-review-checklist.md
    sprint-orchestrator-prompt.md
```

## Базовый workflow

1. Создай issue с конкретной задачей по шаблону `prompts/issue-template-agent-task.md`.
2. Сначала запускай `00-architect` для плана и границ задачи.
3. Потом профильный агент делает изменения в отдельной ветке.
4. `06-test-qa`, `07-security-reviewer` и `09-code-reviewer` проверяют результат.
5. `11-release-manager` готовит changelog, миграции и план выката.

## Жесткие правила

- Агент не должен менять секреты, платежи, прод-конфиги и инфраструктуру без отдельного явного подтверждения.
- Любая задача заканчивается списком измененных файлов, командами проверки и рисками.
- Любой код без тестов считается незавершенным, кроме документации и прототипов.
- Агент обязан читать существующую архитектуру перед правками, а не переписывать проект “с нуля”.

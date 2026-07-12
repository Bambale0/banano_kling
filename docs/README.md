# Documentation Map

Этот каталог теперь разделён на два типа материалов:

- `операционные и продуктовые документы` — поддерживаются по текущему коду
- `provider reference docs` — справочные заметки по внешним API, полезны как вложения, но не заменяют код и тесты

## Актуальные внутренние документы

- [../README.md](../README.md) — overview репозитория
- [architecture.md](architecture.md) — архитектура, компоненты, endpoints, storage, security
- [roadmap.md](roadmap.md) — статус системы и ближайшие приоритеты
- [tracemap.md](tracemap.md) — индекс трассировки пользовательских потоков
- [runbook.md](runbook.md) — эксплуатация, логи, инциденты, restart policy
- [run_guide.md](run_guide.md) — локальный запуск и базовые проверки
- [migration.md](migration.md) — миграции, backfill, repair scripts
- [postgres-migration.md](postgres-migration.md) — PostgreSQL cutover/runtime path

## Специализированные трассировки

- [../tracemap_complete_RU.md](../tracemap_complete_RU.md)
- [../tracemap_generation.md](../tracemap_generation.md)
- [../tracemap_payments.md](../tracemap_payments.md)
- [../tracemap_feed_referral.md](../tracemap_feed_referral.md)
- [../tracemap_credits_check.md](../tracemap_credits_check.md)

## Provider reference docs

Файлы ниже стоит читать как справочные вложения к конкретным интеграциям, а не как описание внутренней архитектуры:

- `kling_api*.md`
- `kie_ai_integration.md`
- `veo_api.md`
- `motion_control_api.md`
- `tbank_api.md`
- `yookassa.md`
- `crypto_api.md`

Если reference-doc конфликтует с runtime, приоритет у:

1. `bot/services/*`
2. `bot/main.py`, `bot/miniapp.py`
3. `tests/*`

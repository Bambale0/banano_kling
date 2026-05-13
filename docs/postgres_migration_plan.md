# PostgreSQL migration foundation

Цель: перевести платёжную/генерационную часть Катиного бота с SQLite на PostgreSQL без одномоментного риска для production.

## Почему

SQLite подходит для старта, но для бота с балансами, платежами, provider webhooks и несколькими параллельными update потоками нужны:

- транзакции с нормальной блокировкой строк;
- audit trail для баланса;
- idempotency для webhook/payment callbacks;
- индексы под частые запросы;
- безопасный backup/restore.

## Этапы

1. **Foundation, текущий этап**
   - добавить целевую PostgreSQL schema draft;
   - оставить production на SQLite;
   - не менять runtime path списаний/начислений;
   - подготовить тестируемые границы для будущего repository layer.

2. **Repository layer**
   - выделить интерфейс для users/payments/generation_tasks/credit ledger;
   - покрыть unit tests на SQLite-compatible fake или temporary SQLite;
   - убрать прямые SQL вызовы из handlers.

3. **Dual-write dry run**
   - писать критичные события в SQLite как primary;
   - параллельно писать ledger/events в PostgreSQL;
   - сравнивать агрегаты баланса.

4. **Cutover**
   - freeze writes на короткое окно;
   - мигрировать users/tasks/payments/referrals;
   - проверить контрольные суммы;
   - переключить DATABASE_URL на postgres;
   - rollback plan: вернуть SQLite primary.

## Минимальная целевая модель

- `users` — профиль пользователя;
- `credit_transactions` — append-only ledger баланса;
- `payments` — платёжные попытки/статусы;
- `generation_tasks` — задачи провайдеров;
- `provider_webhooks` — idempotent обработка webhook payloads;
- `telegram_updates` — idempotent Telegram update tracking;
- `referrals` — реферальные связи;
- `partner_withdrawals` — выплаты партнёрам.

## Инварианты

- баланс = сумма `credit_transactions.amount`;
- любые provider/payment webhook-и обрабатываются idempotently;
- списание за генерацию и создание task происходят в одной транзакции;
- refund привязан к task/payment reason и не может выполниться дважды.

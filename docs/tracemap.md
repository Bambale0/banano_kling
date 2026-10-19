# Исторический индекс трассировок

> Ссылки и карты ниже могут относиться к прежним маршрутам и deployment.
> Текущий маршрут публикаций/повторов описан в
> [PUBLISHED_REPEAT_CONTRACT.md](PUBLISHED_REPEAT_CONTRACT.md);
> API/архитектура — в [architecture.md](architecture.md).
> Проверять целевые ссылки и контракт в коде, прежде чем использовать старую карту.

# Trace Map Index

Ниже собраны актуальные карты потоков по системе. Это не abstract diagrams, а рабочие трассировки от входа до DB/service side effects.

- [../tracemap_complete_RU.md](../tracemap_complete_RU.md) — полная карта системы
- [../tracemap_generation.md](../tracemap_generation.md) — image/video generation и provider completion
- [../tracemap_payments.md](../tracemap_payments.md) — пополнение, webhook, reconcile, idempotency
- [../tracemap_feed_referral.md](../tracemap_feed_referral.md) — feed, prompt library, referrals, deep links
- [../tracemap_credits_check.md](../tracemap_credits_check.md) — где и как валидируется/списывается баланс

Как читать tracemap:

`Источник -> Handler/API -> Validation -> DB write -> Service call -> Webhook/poll -> Final side effects`

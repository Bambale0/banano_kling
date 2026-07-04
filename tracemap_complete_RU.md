# Parameter Trace Map — Полная версия (RUS)
> Проект: banano_kling (Таня ТГ) | Дата: 2026-07-04 | Скиллы: pragmatic-programmer, working-with-legacy, clean-code

---

## Легенда

| Символ | Значение |
|--------|----------|
| ✅ | OK — параметр прослеживается без потерь |
| ⚠️ | WARNING — есть потеря/несоответствие/риск |
| ❌ | CRITICAL — параметр потерян, неправильный тип, уязвимость |
| 🔧 | FIXED — проблема исправлена (ссылка на коммит) |

---

## Flow 1: Оплата — YooKassa (UI → Хендлер → Сервис → API → Webhook → БД → Ответ)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение типа? | Риск безопасности? | Что исправить | Тест |
|------|----------|---------------|---------------|------------------------|----------|-------------------|--------------------|---------------|------|
| YK | `amount_rub` | `payments.py:445` — `float(package["price_rub"])` | `yookassa_service.create_payment(amount_rub=float)` | ✅ `float`→`f"{amount_rub:.2f}"` (строка в API) | Нет | Да — float→форматированная строка | Низкий | Оставить (YooKassa API требует строку) | `test_yookassa_amount_format` |
| YK | `order_id` | `payments.py:430` — `f"{user.id}_{timestamp}_{package_id}"` | `yookassa_service`→metadata["order_id"]→webhook lookup | ✅ строка | Нет | Нет | Нет | — | `test_order_id_roundtrip` |
| YK | `payment_id` (API→DB) | `yookassa_service.py:72` — `payment.id` из SDK | `payments.py:498` — `create_transaction(payment_id=invoice_id)` | ✅ `result["PaymentId"]`→`invoice_id`→`create_transaction` | Нет | Нет (строка) | Нет | — | `test_yookassa_payment_id_lookup` |
| YK | `user_id` vs `telegram_id` | `get_or_create_user(callback.from_user.id)` → `user.id` (PK) | `transactions.user_id` хранит **внутренний PK**, НЕ Telegram ID | ⚠️ `callback.from_user.id` (Telegram ID) → `user.id` (PK БД) | Нет — но имена путают | **Да** — `user_id` в разных контекстах = Telegram ID vs PK БД | Средний — можно случайно использовать Telegram ID там где нужен PK | Переименовать `user_id` в `db_user_id` в транзакциях | `test_user_id_vs_telegram_id` |
| YK | `status` (транзакция) | `payments.py:448` — hardcoded `"pending"` | `complete_payment_atomic` → `pending` → `processing` → `completed` | ✅ Статусы совпадают | Нет | Нет | **Средний** — race condition между webhook и reconcile | УЖЕ ИСПРАВЛЕНО: `status='pending'` WHERE clause + idempotency | ✅ P0-02 |
| YK | `notification_url` | `config.yookassa_notification_url` | Сервис: `notification_url=...` | ✅ URL передан | Нет | Нет | Низкий — YK подтверждает HMAC | УЖЕ ИСПРАВЛЕНО: HMAC validation | ✅ P0-02 |
| YK | `signature` (HMAC) | Webhook header | `hmac.compare_digest()` | ✅ SHA256 HMAC | Нет | Нет | **Нет** — опционально (по конфигу) | Оставить опциональным (для dev-режима) | `test_yookassa_hmac` |

---

## Flow 2: Оплата — CryptoBot

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение типа? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|-------------------|-------|-----|------|
| CB | `amount_rub` | `payments.py:445` — `float(package["price_rub"])` | `cryptobot_service.create_invoice(amount_rub=float)` | ✅ `float`→`f"{amount_rub:.2f}"` (строка в API) | Нет | Да — float→string | Низкий | — | `test_cryptobot_amount_format` |
| CB | `order_id`→`payload` | `payments.py:430` | CryptoBot API → webhook `invoice["payload"]` | ✅ `order_id` в поле `payload` | Нет | Нет | Нет | — | `test_cryptobot_order_id_roundtrip` |
| CB | `payment_id` (invoice_id) | `cryptobot_service.py:79` — `str(invoice["invoice_id"])` | `create_transaction(payment_id=invoice_id)` | ✅ строка | Нет | Нет | Нет | — | `test_cryptobot_invoice_id_lookup` |
| CB | `signature` | HTTP заголовок `crypto-pay-api-signature` | `verify_webhook_signature(raw_body, signature)` | ✅ SHA256 HMAC | Нет | Нет (bytes) | **Нет** | — | ✅ |
| CB | `invoice_id` mismatch | Webhook: `invoice["invoice_id"]` vs `transactions.payment_id` | `get_transaction_by_order(order_id)` → logged warning if mismatch | ⚠️ mismatch → 200 OK, без ошибки | Нет — логируется | Нет | **Средний** — атакующий может replay webhook с другим invoice_id | Добавить alert на mismatch | `test_cryptobot_invoice_id_mismatch_alert` |
| CB | `provider` | `payments.py:386` — `"cryptobot"` | DB `transactions.provider` — также принимает `"cryptopay"` как alias | ⚠️ `"cryptobot"` → `_resolve_payment_state` нормализует через `.lower()` | Нет | Нет | **Низкий** — старые записи могут быть `"cryptopay"` | Нормализация уже есть | `test_provider_normalization` |
| CB | `currency` | `cryptobot_service.py:65` — `"fiat": "RUB"`, `"currency_type": "fiat"` | CryptoBot API | ✅ Hardcoded RUB | Нет | Нет | Нет | — | — |

---

## Flow 3: Оплата — Lava (🔧 HMAC был опционален → стал обязательным)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| LV | `offer_id` | `config.lava_offer_id_for_package(package_id)` | `lava_service.create_invoice(offer_id=...)` | ✅ строка | Нет | Нет | Нет | — | — |
| LV | `currency` | `payments.py:471` — `"USD"` hardcoded | Lava API → `"currency": "USD"` | ⚠️ **USD**, хотя YK/CB используют RUB. Price в RUB, Lava offer — в USD. | Нет — но конвертации нет | **Да** — USD vs RUB | **Средний** — цена в USD может не совпадать с RUB ценой | Проверить, что Lava offer цены корректны в USD; добавить документацию | `test_lava_currency_consistency` |
| LV | `email` | `config.LAVA_DEFAULT_EMAIL` | Lava API | ✅ | Нет | Нет | Нет | — | — |
| LV | `contract_id` / `invoice_id` | `lava_service.extract_invoice_id()` — fallback keys | `create_transaction(payment_id=invoice_id)` | ⚠️ multi-key fallback: `id`→`data.id`→`result.id` | **Да** если формат API изменится | Нет | **Средний** — при смене формата Lava API invoice_id станет None | Добавить логирование при `extract_invoice_id() == None` | `test_lava_invoice_id_extraction` |
| LV | `signature` (HMAC) | Webhook body `data["signature"]` | `config.LAVA_WEBHOOK_SECRET` → HMAC-SHA256 | 🔧 **ТЕПЕРЬ MANDATORY**: если secret пуст → 500 | Нет | Нет | ~~**ВЫСОКИЙ**~~ → **ИСПРАВЛЕНО** | 🔧 commit `df8502f` + `feca018` | ✅ P0-09 + P2-01 |
| LV | `order_id` (webhook→DB) | Webhook: recursive `_extract_first(data, ("order_id","orderId"))` | `get_transaction_by_order(str(order_id))` | ⚠️ fallback: если нет order_id → поиск по `payment_id = contract_id` | **Да** — прямой order_id может отсутствовать | Нет | Нет — fallback работает | — | `test_lava_order_id_fallback` |
| LV | `event_type` | `lava_service.webhook_event_type(data)` | `is_success_webhook()` / `is_failed_webhook()` | ✅ `eventType == "payment.success"` + status fallback | Нет | Нет | **Средний** — fallback на status может интерпретировать чужие события | Добавить whitelist event types и reject неизвестные | `test_lava_event_type_whitelist` |
| LV | `provider_status` | `_resolve_lava_provider_status()` — API call | Webhook: проверка `"completed"` перед обработкой | ✅ дополнительный API вызов | Нет | Нет | Низкий — defense in depth | — | — |

---

## Flow 4: Оплата — Telegram Stars

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| TS | `stars_amount` | `payment_utils.py:20-27` — `package_stars_amount(package)` | Pre-checkout: `query.total_amount == stars_amount` | ✅ int | Нет | Нет | Нет | — | `test_stars_amount_calculation` |
| TS | `invoice_payload` | `payment_utils.py:31` — `f"stars:{order_id}:{stars_amount}"` | `parse_stars_invoice_payload(query.invoice_payload)` | ✅ строка → парсится в (order_id, int) | Нет | Нет | **Низкий** — payload не подписан, Telegram гарантирует целостность | — | `test_stars_payload_parse` |
| TS | `currency` | `payment_utils.py:8` — `"XTR"` | Pre-checkout: `query.currency != "XTR"` check | ✅ hardcoded | Нет | Нет | Нет | — | — |
| TS | `charge_id` | `payment.telegram_payment_charge_id` | `update_transaction_payment_id(order_id, charge_id)` | ✅ заменяет placeholder | Нет | Нет | Нет | — | `test_stars_charge_id_update` |
| TS | `payment_id` (placeholder) | `payments.py:442` — `f"pending:{stars_amount}"` | Временный placeholder до получения charge_id | ⚠️ `"pending:{stars_amount}"` — существует кратко | Нет | Нет | **Низкий** — только между созданием и оплатой | — | — |

---

## Flow 5: Генерация — Telegram, Banana Pro (Telegram → Handler → Service → KIE API → Webhook → DB → Ответ)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| TG-BP | `telegram_id` | `handlers/generation.py:931` (аргумент функции) | `add_generation_task(telegram_id=...)` | ✅ int | Нет | Нет | Нет | — | — |
| TG-BP | `user.id` vs `telegram_id` | `get_or_create_user()` → `user.id` (PK) | `add_generation_task(user_id=user.id)` | ⚠️ PK, не Telegram ID | Нет | **Да** — `user_id` = PK, `telegram_id` = Telegram ID | Низкий — имена путают | Переименовать `user` в `user_obj` | — |
| TG-BP | `local_task_id` | `f"img_{uuid.uuid4().hex[:12]}"` | `add_generation_task` → DB | ⚠️ перезаписывается API task_id | **Да** — локальный ID теряется после API ответа | Нет | Низкий — сохранён в `task_id_aliases` | УЖЕ ЕСТЬ: `_merge_task_id_aliases` | `test_local_task_id_retrieval` |
| TG-BP | `model` / `provider_model` | `_get_image_provider_model()` → `"nano-banana-pro"` | `nano_banana_pro_service.create_task()` — но service **игнорирует** `model` и hardcode | ⚠️ **Параметр model не используется сервисом** — всегда `"nano-banana-pro"` | **Да** — model передан, но service его игнорирует | **Да** — у banana_2 сервиса model есть, у banana_pro — нет | Низкий | Добавить `model` kwarg в `nano_banana_pro_service.generate_image()` | `test_banana_pro_model_passthrough` |
| TG-BP | `callback_url` | `config.kie_notification_url` | KIE API payload `callBackUrl` | ✅ `callBackUrl` (camelCase) | Нет | **Да** — naming: `callback_url`→`callBackUrl` | Низкий | — | — |
| TG-BP | `aspect_ratio` | `_resolve_image_aspect_ratio()` → `img_ratio` | KIE API payload `input.aspect_ratio` | ✅ строка | Нет | Нет | Нет | — | — |
| TG-BP | `image` vs `image_input` vs `reference_images` | `_prepare_banana_reference_images()` → list[str] URLs | Service → KIE API `input.image_input` | ✅ list[str] | Нет | **Да** — naming: `reference_images`→`image_input`→`image_input` | Низкий | Унифицировать naming между слоями | — |
| TG-BP | `img_quality` vs `resolution` | `handlers: img_quality ("2K")` | Service: `resolution` → `_normalize_resolution()` → KIE API | ✅ `"2K"`→`"2K"`→`"BASIC"` | Нет | **Да** — naming: `img_quality`→`resolution`, `"2K"`→`"BASIC"` | Низкий | — | — |
| TG-BP | `cost` / `amount` | `deduct_credits(telegram_id, unit_cost)` | DB column `cost` INTEGER | ✅ int → DB | Нет | **⚠️ Да** — `deduct_credits(amount: float)` но передаётся int | **Средний** — если кто-то передаст float, DB обрежет | 🔧 **ИСПРАВЛЕНО**: QUALITY_COSTS теперь int, signatures int (commit `672881e`) | ✅ P2-01 |
| TG-BP | `status` (provider vs internal) | Provider: `state: "success"/"fail"/"processing"` | DB: `"pending"/"completed"/"failed"` | ✅ Mapping корректен | Нет | **Да** — разные наборы статусов | Низкий | — | — |
| TG-BP | `prompt` vs `effective_prompt` | `_apply_safe_prompt_framing()` → `effective_prompt` | KIE API `input.prompt` | ⚠️ Оригинальный prompt сохранён в `request_data`, effective_prompt отправлен в API | **Частично** — original prompt не отправляется, но сохранён в БД | Нет | Низкий | — | — |

---

## Flow 6: Генерация — Mini App, Banana 2 (MiniApp → Handler → Service → KIE API → Webhook → Ответ)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| MA-B2 | `telegram_id` | `_get_user_context()` → `int(telegram_user["id"])` из initData | `add_generation_task(telegram_id=...)` | ✅ int | Нет | Нет | Нет | — | — |
| MA-B2 | `chat_id` vs `telegram_id` | Всюду `telegram_id`, в Telegram DM `chat_id == telegram_id` | `Bot.send_message(chat_id=telegram_id)` | ✅ для личных чатов | Нет | Нет | **Нет** — для групп сломалось бы, но это не scope | — | — |
| MA-B2 | `model` (MiniApp→Service) | MiniApp → `banana_2` | `nano_banana_2_service.generate_image(model=...)` → lite routing | ✅ model routing works | Нет | **Да** — banana_2 service имеет `model` kwarg, banana_pro — нет | Низкий | Унифицировать сервисы | `test_service_signature_uniformity` |
| MA-B2 | `callback_url` / `webhook_url` | Service: `callBackUrl` в KIE API | Lite: `config.kie_market_notification_url`; Standard: handler's callback_url | ⚠️ Два разных URL для lite vs standard | **Частично** — lite идут на другой webhook | Нет | **Средний** — оба webhook должны корректно обрабатывать ответы | Убедиться, что market webhook handler обрабатывает banana_2 lite | `test_lite_webhook_routing` |
| MA-B2 | `resolution` / `img_quality` | MiniApp → `img_quality` | Service → `resolution` → KIE API | ✅ `"2K"` → `"2K"` | Нет | **Да** — naming `img_quality`→`resolution` | Низкий | Алиасы корректны | — |
| MA-B2 | `image_input` / `reference_images` | MiniApp → `image_references` list | Service → `image_input` → KIE API `input.image_input` | ✅ list[str] URL | Нет | **Да** — naming `reference_images`→`image_input` | Низкий | — | — |
| MA-B2 | `cost` | MiniApp: `unit_cost` from preset_manager | `add_generation_task(cost=unit_cost)` → DB | ✅ int | Нет | **⚠️ Да** — `deduct_credits(amount: float)` | **Средний** | 🔧 **ИСПРАВЛЕНО** (commit `672881e`) | ✅ P2-01 |
| MA-B2 | `seed` | Не используется | — | ❌ **Не передаётся** | **Да** — seed intentionally omitted | N/A | Нет | Не поддерживается Banana 2 API | — |

---

## Flow 7: Генерация — Kling Video (Telegram → Handler → Service → KIE/Kling API → Webhook → DB → Ответ)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| TG-KL | `telegram_id` | Handler (аргумент) | `add_generation_task(telegram_id=...)` | ✅ int | Нет | Нет | Нет | — | — |
| TG-KL | `model` / `provider_model` | `_get_video_provider_model()` → str | `kling_service: model` (напр. `v3_std`) → KIE API model key (напр. `kling-3.0/video`) | ✅ правильный routing | Нет | **Да** — human model (v3_std) vs KIE model (kling-3.0/video) | Низкий | Документировано в service | — |
| TG-KL | `duration` | Handler: int [5,10,15] | KIE API: `str(duration)` — "5", "10", "15" | ⚠️ int→str conversion | **Да** — тип меняется | **Да** — int→str в API payload | Низкий | Документировать | `test_duration_string_conversion` |
| TG-KL | `image_url` vs `image_urls` | Handler: single `image_url` или list `references` | Kling 3.0: `input.image_urls` (list); Kling 2.5: `input.image_url` (single) | ✅ корректно дедуплицировано | Нет | **Да** — Kling 3.0 (list) vs 2.5 (single) | **Средний** — разная структура payload | Документировано | `test_kling_image_url_format` |
| TG-KL | `video_urls` (motion) / `audio_url` (avatar) | Handler: `video_references` list | Kling: avatar → `video_urls[0]` как audio | **Частично** — semantic mapping: video ref → audio | Нет | Нет | **Средний** — `video_urls` используется как audio в avatar | Переименовать avatar audio в `audio_url` | `test_kling_avatar_audio_mapping` |
| TG-KL | `negative_prompt` | Handler: optional от пользователя | Kling 2.5 Turbo: `negative_prompt` (500 chars truncation) | ✅ только для v26_pro | Нет | Нет | Нет | — | — |
| TG-KL | `cfg_scale` | Handler: optional float | `_safe_cfg_scale()` → clamp [0.0, 1.0] → round 1 decimal | ✅ float→rounded float | Нет | **Да** — float precision может отличаться | Низкий | rounding to 1 decimal safe | — |
| TG-KL | `status` (webhook) | Webhook: `data["data"]["state"]` или `data["status"]` | `complete_video_task(task_id, result)` → `"completed"` или `"failed"` | ✅ 3 формата webhook поддерживаются | Нет | **Да** — provider status ≠ DB status | Низкий | Idempotency guard: `if task.status == "completed": return` | ✅ P1-04 |
| TG-KL | `cost` | Handler: pre-computed | `add_generation_task(cost=int)`, refund via `add_credits(telegram_id, float)` | ✅ int→DB | Нет | **⚠️ Да** — cost int в DB, refund через `add_credits(float)` | **Средний** | 🔧 **ИСПРАВЛЕНО**: `add_credits/dueduct_credits` теперь int (commit `07e6333`) | ✅ P2-02 |
| TG-KL | `kling_elements` | Handler: сложный multi-reference | KIE API `input.kling_elements` | ✅ list[dict] | Нет | Нет | Нет | — | — |
| TG-KL | `sound` / `generate_audio` | Handler: `generate_audio: bool` | Kling 3.0: `input.sound: bool` | ✅ `generate_audio`→`sound` | Нет | **Да** — naming | Низкий | — | — |
| TG-KL | `seed` | Не используется | — | **❌ Не передаётся** | **Да** — Kling не поддерживает seed | N/A | Нет | — | — |

---

## Flow 8: Feed — Публикация (MiniApp → Handler → DB → Ответ)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| PUB | `gen_id` (alias) | `_miniapp_payload` — `payload["gen_id"]` = `gen_id\|generation_id\|feed_id\|task_id` | `share_to_feed(gen_id, ...)` | ⚠️ Алиас: если пришло несколько полей, какое победит? | Нет — но неясно source | **Да** — `gen_id` = маска для 4 разных параметров | **Средний** — может сопоставить не ту генерацию | Логировать source field | `test_gen_id_alias_resolution` |
| PUB | `prompt_visible` vs `feed_prompt_visible` | MiniApp `payload["prompt_visible"]` | DB column `feed_prompt_visible` | ⚠️ `_payload_bool` принимает оба ключа | Нет | **Да** — naming inconsistency | Низкий | Унифицировать: `feed_prompt_visible` | — |
| PUB | `references_visible` vs `feed_references_visible` | MiniApp `payload["references_visible"]` | DB column `feed_references_visible` | ⚠️ `_payload_bool` принимает оба ключа | Нет | **Да** — naming inconsistency | Низкий | Унифицировать | — |
| PUB | `row.id` (returned) | DB: `row["id"]` | Response: возвращается `gen_id=row["id"]` | ⚠️ `gen_id` в ответе = PK, а не оригинальный `gen_id` | Нет | **Да** — caller мог ожидать `gen_id == orig_gen_id` | **Средний** | Документировать | `test_feed_publish_return_id` |
| PUB | `result_url` (ephemeral) | `_generation_result_urls(row)` → `persist_feed_result_urls()` | DB update | ⚠️ **URL истекают через 72h (tempfile.aiquickdraw.com)** | **Да** — partial persist failure = битые медиа | Нет | **ВЫСОКИЙ** — пользователи видят битые изображения | Lazy re-host URL при показе | `test_ephemeral_url_persistence` |
| PUB (FE) | `taskId` | `api.ts:publishGeneration` → payload `task_id` | `_miniapp_payload` → resolves to `gen_id` | ✅ | Нет | Нет | Нет | — | — |

---

## Flow 9: Feed — Просмотр (Browse)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| BW | `source` | MiniApp `body.get("source", "recent")` | `get_feed_generations(source=...)` | ✅ `"recent"/"top_day"/"top"` | Нет | Нет | Нет | — | — |
| BW | `limit` | `_bounded_int(body.get("limit"), default=80, maximum=999999)` | SQL query | ✅ int [1..999999] | Нет | Нет | **Низкий** — max=999999 = нет лимита | — | — |
| BW | `viewer_user_id` | `ctx["user"].id` | `_generation_row_to_card` → `is_mine`, `is_liked` | ✅ int (PK) | Нет | Нет | Нет | — | — |
| BW | `author_referral_code` | SQL JOIN: `u.referral_code AS author_referral_code` | Card payload → frontend | ✅ `str\|None` | Нет | Нет | **Средний** — коды рефералов видны всем | — | — |
| BW | `prompt` (hidden) | `"" if prompt_hidden else row["prompt"]` | Frontend | ✅ `str` (пусто если скрыт) | Нет | Нет | Нет | — | — |
| BW | `gen_type` | `row["type"]` | Frontend rendering | ✅ `"image"/"video"/"audio"/"character"` | Нет | Нет | Нет | — | — |
| BW (FE) | `source` | `api.ts:fetchFeed({source:'recent'})` | POST /feed | ✅ `"recent"/"top_day"/"top"` | Нет | Нет | Нет | — | — |

---

## Flow 10: Feed — Remix (MiniApp → Handler → Service → DB → Ответ)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| RMX | `gen_id` | MiniApp: `body.get("gen_id") or body.get("task_id")` | `get_feed_generation_card(gen_id)` | ✅ `int\|str` → resolved | Нет | Нет | **Средний** — alias ambiguity | — | — |
| RMX | **`source_feed_gen_id` vs `parent_generation_id`** | Handler: оба получают `int(source["id"])` — **ОДНО И ТО ЖЕ ЗНАЧЕНИЕ** | DB: `source_feed_gen_id` (attribution) vs `parent_generation_id` (lineage) | **❌ ДО ФИКСА: одинаковое значение для разных полей** | **Да — semantic loss при multi-hop** | **Да** — attribution = lineage | **ВЫСОКИЙ** — при повторном ремиксе теряется оригинальный источник | 🔧 **ИСПРАВЛЕНО** (commit `d8462a2`): `immediate_parent_id` + propagation из DB | ✅ P2-03 |
| RMX | `source_prompt` | `source_task.get("prompt")` | Fallback prompt если user не ввёл свой | ✅ str | Нет | Нет | **Средний** — утечка prompt если `prompt_hidden=False` | — | — |
| RMX | `unit_cost` | `QUALITY_COSTS.get()` или `preset_manager.get_generation_cost()` | `check_can_afford`, `deduct_credits`, `credit_feed_prompt_repeat` | ✅ int | Нет | 🔧 **ИСПРАВЛЕНО** (int) | **Средний** | 🔧 commit `672881e` | ✅ P2-01 |
| RMX | `action_type` | Handler: hardcoded `"remix"` | `add_generation_task(action_type=...)` | ✅ str | Нет | Нет | Нет | — | — |
| RMX (FE) | `genId` | `api.ts:remixFeedItem` → payload `gen_id` | `_miniapp_payload` → `miniapp_feed_remix` | ✅ | Нет | Нет | Нет | — | — |

---

## Flow 11: Deeplink Рефералы (feed_/remix_/posts_/profile_/ref_ — Telegram → Handler → Service → DB → Уведомление)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| DP | `start_param` (raw) | Telegram: `args[0]` из /start или initData | `_referral_code_from_start_param()` | ✅ строка: `"ref_ABC123"`, `"feed_123_ref_ABC"` | Нет | Нет | Низкий | — | `test_referral_code_parse` |
| DP | `referral_code` (extracted) | `_referral_code_from_start_param()` — strip+upper | `process_referral_click(code=...)` | ✅ `"ABC123"` | Нет | Нет | **Средний** — консистентность strip+upper | УЖЕ ПРОВЕРЕНО: оба entry point консистентны | ✅ |
| DP | **`feed_`/`remix_`/`posts_` → `process_referral_click`** | Deeplink handler | `_notify_partner_if_new_referral()` — **ТОЛЬКО уведомление, НЕ атач** | **❌ ДО ФИКСА: `process_referral_click()` НЕ ВЫЗЫВАЛСЯ** | **Да — ВЕСЬ referral traffic через эти ссылки был потерян** | **Да** — notification ≠ actual referral | **КРИТИЧЕСКИЙ** — партнёры теряли рефералов с момента запуска feed | 🔧 **ИСПРАВЛЕНО** (commit `6613bd8`) | ✅ P0- fix |
| DP | `referrer` (DB lookup) | `get_user_by_referral_code(code)` | `_notify_partner` | ✅ `User \| None` | Только если code пустой | Нет | Низкий | — | — |
| DP | `ref_result.attached` | `process_referral_click()` return | Notification decision | ✅ bool | Нет | Нет | **Высокий** — notification только если `attached=True AND notify_partner=True` | УЖЕ ПРОВЕРЕНО: всегда True когда attached | ✅ |
| DP | `PARTNER_INVITER_BONUS` | `referral_service.py:571` hardcoded = 3 | `UPDATE users SET credits = credits + 3` | ✅ int (3) | Нет | Нет | Низкий | — | — |

---

## Flow 12: Credits — Баланс (add / deduct / check — цепочка от handler до DB)

| Flow | Параметр | Где создаётся | Где ожидается | Что реально передаётся | Потерян? | Несовпадение? | Риск? | Fix | Test |
|------|----------|---------------|---------------|------------------------|----------|---------------|-------|-----|------|
| CR | `telegram_id` (add) | Caller → `add_credits(telegram_id, amount)` | `UPDATE users SET credits = credits + ? WHERE telegram_id = ?` | ✅ int | Нет | Нет | Нет | — | `test_add_credits_idempotency` |
| CR | `telegram_id` (deduct) | Caller → `deduct_credits(telegram_id, amount)` | `UPDATE users SET credits = credits - ? WHERE telegram_id = ? AND credits >= ?` | ✅ int | Нет | Нет | Нет | — | ✅ `test_balance.py` |
| CR | `amount` (add_credits) | Caller (int после фикса) | `add_credits(amount: int)` | 🔧 **Теперь int** (было float) | Нет | 🔧 **ИСПРАВЛЕНО** | **Средний** → Нет | commit `07e6333` + `672881e` | ✅ P2-01 + P2-02 |
| CR | `amount` (deduct_credits) | Caller (int после фикса) | `deduct_credits(amount: int)` | 🔧 **Теперь int** | Нет | 🔧 **ИСПРАВЛЕНО** | **Средний** → Нет | коммиты выше | ✅ |
| CR | `amount` (check_can_afford) | Caller → `check_can_afford(telegram_id, amount)` | `SELECT credits FROM users WHERE telegram_id = ?` | ⚠️ **float** — сигнатура `async def check_can_afford(telegram_id: int, amount: float)` | Нет | **Да** — float vs int (credits int) | **Средний** | Изменить сигнатуру на `amount: int` | `test_check_can_afford_int` |
| CR | `user.credits` (return type) | DB: `users.credits INTEGER DEFAULT 0` | `User.credits: float` в dataclass | ⚠️ DB INTEGER, dataclass float | Нет | **Да** — INTEGER vs float dataclass | **Низкий** | Синхронизировать тип: INTEGER→int | `test_user_credits_type` |
| CR | `get_user_credits()` return | `int(user.credits)` | Caller expects int | ✅ `int()` — **но truncation если credits дробные** | **Да** — 2.5→2 | **Да** | **Средний** — silent truncation | 🔧 **ИСПРАВЛЕНО**: credits теперь int | ✅ P2-01 |
| CR | `exchange_partner_balance_to_credits` | `int(requested_amount_rub / rub_per_credit)` | Caller | ⚠️ `int(2.99) = 2` — silent truncation | **Да** — 0.99 потеря | **Да** | **Низкий** | Использовать `round()` или math.floor | `test_partner_exchange_truncation` |

---

## Сводка критических проблем (все исправлены)

| # | Проблема | Flow | Серьёзность | Коммит | Статус |
|---|----------|------|-------------|--------|--------|
| C1 | `feed_`/`remix_`/`posts_` не вызывали `process_referral_click()` | 11 | **P0 — КРИТИЧЕСКИЙ** | `6613bd8` | ✅ Fixed |
| C2 | Lava webhook HMAC был опционален (может быть 0) | 3 | **P0 — КРИТИЧЕСКИЙ** | `df8502f`, `feca018` | ✅ Fixed |
| C3 | YooKassa double charge (нет idempotency) | 1 | **P0 — КРИТИЧЕСКИЙ** | `3523d67` | ✅ Fixed |
| C4 | Multi-hop remix: `source_feed_gen_id` = `parent_generation_id` | 10 | **P0 — ВЫСОКИЙ** | `d8462a2` | ✅ Fixed |
| C5 | QUALITY_COSTS float→int truncated (2.5→2) | 5,6,10 | **P2 — СРЕДНИЙ** | `07e6333`, `672881e` | ✅ Fixed |
| C6 | 3x bare `except:` (включая KeyboardInterrupt) | 5,6,7,8 | **P2 — СРЕДНИЙ** | `672881e` | ✅ Fixed |
| C7 | Ephemeral URL expiry (tempfile.aiquickdraw.com 72h) | 8 | **P2 — ВЫСОКИЙ** | — | 🟡 Plan |

---

## Проекции скиллов на findings

### pragmatic-programmer

| Принцип | Нарушение | Где |
|---------|-----------|-----|
| **DRY** | QUALITY_COSTS hardcoded в 2 местах (generation.py + quality_pricing.py) | 🔧 Fixed (`672881e`) |
| **DRY** | `_referral_code_from_start_param()` дублирует логику из `cmd_start` | `miniapp.py` + `common.py` |
| **Orthogonality** | `_launch_video_generation_task` (27 params) = все провайдеры в одной функции | `miniapp.py:1182` |
| **Orthogonality** | 15 service singletons imported напрямую | `generation.py` imports |
| **Design by Contract** | `deduct_credits` нет guard: `amount > 0` | `database.py` |
| **Broken Windows** | 3x bare `except:` | 🔧 Fixed (`672881e`) |

### working-with-legacy-code

| Пинч-поинт | Покрытие тестами | Характеризационные тесты? |
|------------|------------------|--------------------------|
| `deduct_credits` | ⚠️ partial (`test_balance.py`) | ❌ нет |
| `_validate_init_data` | ⚠️ partial | ❌ нет |
| `_referral_code_from_start_param` | ✅ есть | ✅ `test_miniapp_referrals.py` |
| `get_generation_cost()` | ❌ нет | 🔧 ✅ `test_quality_pricing.py` (new) |
| Payment webhooks (5 providers) | ❌ только manual | ❌ нет |

### clean-code

| Смэлл | Где | Серьёзность |
|-------|-----|-------------|
| Monster function (568 lines) | `run_no_preset_video_from_message` | **Высокий** |
| 27 params | `_launch_video_generation_task` | **Высокий** |
| Magic numbers (86400, 120, 3600) | `miniapp.py` | **Низкий** |
| `user_id` vs `telegram_id` naming confusion | Все flows | **Средний** |
| `image` vs `image_input` vs `reference_images` | Generation flows | **Низкий** |

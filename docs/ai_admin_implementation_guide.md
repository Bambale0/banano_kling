# Инструкция по внедрению ИИ-админа в Telegram-бот

Документ описывает, как создать в похожем Aiogram-проекте агентного ИИ-админа: админ пишет задачу обычным языком, ассистент строит план, выполняет разрешённые инструменты, хранит контекст сессии, анализирует логи, делает отчёты и research по новым AI-инструментам.

## 1. Цель

ИИ-админ должен закрывать четыре класса задач:

- Операционное управление: статистика, пользователь, баланс, бан/разбан, техрежим, промокоды, экспорт.
- Агентные отчёты: несколько шагов подряд, например статистика → техрежим → промокоды → анализ логов.
- Диагностика: анализ последних логов и объяснение вероятных причин ошибок.
- Research: поиск и краткий анализ новых AI-моделей, API и провайдеров для генерации контента.

Ключевой принцип: модель не должна напрямую менять данные. Она только возвращает план. Код валидирует план и выполняет только заранее разрешённые действия.

## 2. Архитектура

Рекомендуемая структура:

```text
bot/
  handlers/
    admin.py                 # UI, FSM, подтверждения, выполнение tool actions
  services/
    admin_ai_service.py      # planner: LLM -> JSON plan + fallback parser
  states.py                  # AdminStates.waiting_ai_request / confirming_ai_action
  keyboards.py               # кнопки админки
tests/
  test_admin_ai_service.py   # fallback planner, safety, actions
```

Поток:

```text
Админ -> текст -> planner -> JSON plan -> validation
  -> read-only action: выполнить сразу
  -> mutating action: показать план -> подтверждение -> выполнить
  -> multi-step actions: выполнить шаги по очереди -> общий отчёт
```

## 3. Список инструментов

Начните с минимального allowlist. Не добавляйте произвольный shell, SQL или eval.

Read-only:

```python
READ_ONLY_ACTIONS = {
    "stats",
    "user_info",
    "maintenance_status",
    "list_promos",
    "bot_report",
    "analyze_logs",
    "research_ai",
    "help",
}
```

Mutating:

```python
MUTATING_ACTIONS = {
    "add_credits",
    "deduct_credits",
    "ban_user",
    "unban_user",
    "maintenance_set",
    "create_promo",
    "deactivate_promo",
}
```

Дополнительно можно разрешить `export_users`, но он должен требовать подтверждение, потому что выгружает персональные данные.

## 4. Формат плана от модели

Просите модель возвращать строго JSON:

```json
{
  "action": "stats",
  "params": {},
  "actions": [
    {"action": "stats", "params": {}, "summary": "Собрать статистику"}
  ],
  "summary": "Короткое описание для админа",
  "confidence": 0.8
}
```

Правила:

- `action` должен быть из allowlist.
- `actions` используется для агентного прогона из нескольких шагов.
- если параметров не хватает, модель возвращает `unknown`.
- любые изменения данных требуют подтверждения в UI.
- массовую рассылку лучше не выполнять через ИИ: оставьте штатный ручной раздел.

## 5. Planner service

Создайте сервис `bot/services/admin_ai_service.py`.

Задачи сервиса:

- вызвать LLM;
- извлечь JSON;
- нормализовать `action`, `params`, `actions`;
- очистить параметры: ID, суммы, даты, код промокода;
- добавить fallback parser, если LLM недоступна.

Минимальный prompt:

```text
Ты планировщик админ-действий Telegram-бота.
Верни строго один JSON без markdown.

Доступные action:
stats, user_info, add_credits, deduct_credits, ban_user, unban_user,
maintenance_status, maintenance_set, create_promo, deactivate_promo,
list_promos, export_users, bot_report, analyze_logs, research_ai,
clear_context, help, unknown.

Для сложных запросов верни actions со списком шагов.
Не придумывай ID, суммы, коды и даты.
Если данных не хватает, action=unknown.
Массовую рассылку не выполняй через ИИ.
```

Fallback parser нужен обязательно. Он должен понимать базовые команды:

```text
покажи статистику
проверь пользователя 123456789
начисли 50 BoomCoin пользователю 123456789
спиши 10 BoomCoin у 123456789
включи техрежим
создай промокод VIP20 скидка 20 лимит 100
проанализируй последние логи
сделай отчёт по боту
найди новые ИИ для генерации контента
```

## 6. FSM states

Добавьте состояния:

```python
class AdminStates(StatesGroup):
    waiting_ai_request = State()
    confirming_ai_action = State()
```

В FSM data храните:

```python
{
    "admin_ai_plan": {...},
    "admin_ai_memory": [
        {
            "request": "...",
            "plan": {"action": "...", "actions": ["stats", "analyze_logs"]},
            "result": "..."
        }
    ]
}
```

Ограничивайте память последними 6-8 записями и режьте длинные результаты.

## 7. Кнопки

В основную админку добавьте:

```python
builder.button(text="🤖 ИИ-админ", callback_data="admin_ai")
builder.button(text="📘 Инструкция ИИ", callback_data="admin_ai_help")
```

Внутри ИИ-админа:

```python
InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📘 Инструкция", callback_data="admin_ai_help")],
    [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
    [InlineKeyboardButton(text="🏠 Домой", callback_data="back_main")],
])
```

Для подтверждения:

```python
InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Выполнить", callback_data="admin_ai_confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_ai_cancel"),
    ],
    [InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_back")],
])
```

## 8. Handler flow

Основные хендлеры:

- `/admin_ai` — открыть ИИ-админ.
- `admin_ai` callback — открыть ИИ-админ из панели.
- `admin_ai_help` callback — показать инструкцию.
- message in `waiting_ai_request` — построить план.
- `admin_ai_confirm` — выполнить сохранённый план.
- `admin_ai_cancel` — отменить план.

Логика обработки текста:

```python
plan = await admin_ai_service.plan_action(
    message.text,
    context={
        "admin_id": message.from_user.id,
        "session_memory": memory[-6:],
        "maintenance_mode": await get_bot_setting("maintenance_mode", "0"),
    },
)

error = validate_plan(plan)
if error:
    await message.answer(error)
    return

if plan["requires_confirmation"]:
    await state.update_data(admin_ai_plan=plan)
    await state.set_state(AdminStates.confirming_ai_action)
    await show_plan_preview(plan)
    return

result = await execute_plan(plan)
await remember_context(request, plan, result)
```

## 9. Validation

Никогда не доверяйте JSON от модели.

Проверяйте:

- action входит в allowlist;
- user_id — int;
- amount — положительное число;
- promo code очищен от лишних символов;
- дата строго `YYYY-MM-DD`;
- mutating action требует confirmation;
- actions list не длиннее 5-6 шагов.

Пример:

```python
def validate_plan(plan: dict) -> str | None:
    if plan.get("action") == "unknown":
        return plan.get("summary") or "Не понял действие."

    for item in plan.get("actions", []) or []:
        error = validate_plan(item)
        if error:
            return error

    action = plan["action"]
    params = plan.get("params") or {}

    if action in {"user_info", "add_credits", "deduct_credits", "ban_user", "unban_user"}:
        if not params.get("telegram_id"):
            return "Нужен Telegram ID пользователя."

    if action in {"add_credits", "deduct_credits"} and not params.get("amount"):
        return "Нужна сумма."

    return None
```

## 10. Исполнение действий

Создайте `execute_admin_ai_action(action, params, admin_id, message)`.

Примеры:

```python
if action == "stats":
    return format_admin_stats(await get_admin_stats())

if action == "user_info":
    return format_user_stats(user_id, await get_user_stats(user_id))

if action == "add_credits":
    await add_credits(
        user_id,
        amount,
        reason="admin_ai_adjustment_add",
        external_id=f"admin_ai:{admin_id}:add:{user_id}:{message.message_id}",
        metadata={"admin_id": admin_id},
    )
```

Для списания используйте idempotency key через `external_id`, если в проекте есть ledger. Это защищает от двойного нажатия.

## 11. Агентные цепочки

`bot_report` можно реализовать как цепочку:

```python
actions = [
    {"action": "stats", "params": {}},
    {"action": "maintenance_status", "params": {}},
    {"action": "list_promos", "params": {}},
    {"action": "analyze_logs", "params": {"lines": 250}},
]
```

Executor:

```python
async def execute_plan(plan):
    if not plan.get("actions"):
        return await execute_action(plan["action"], plan["params"])

    sections = []
    for index, item in enumerate(plan["actions"], start=1):
        result = await execute_action(item["action"], item.get("params") or {})
        sections.append(f"Шаг {index}: {item['action']}\n{result}")
    return "\n\n".join(sections)
```

## 12. Анализ логов

Разрешайте только заранее заданные источники:

```python
LOG_PATHS = [
    Path("logs/bot.log"),
    Path("logs/bot_output.log"),
    Path("logs/watchdog.log"),
]
```

Не давайте модели выполнять:

- `cat`;
- `journalctl`;
- `grep`;
- произвольный shell.

Код сам читает хвост файлов, считает метрики и отправляет в LLM:

```python
metrics = {
    "ERROR": count_errors,
    "WARNING": count_warnings,
    "WEBHOOK": count_webhook_lines,
    "RESTART": count_restarts,
}
```

Prompt для анализа:

```text
Проанализируй логи Telegram-бота для админа.
Дай краткий отчёт: что происходит, ошибки/риски, вероятная причина, что проверить дальше.
Если критичных ошибок нет, скажи это явно.
```

Если LLM недоступна, покажите fallback: счётчики и последние ERROR/WARNING строки.

## 13. Research по новым AI

Для research используйте LLM с web search.

Prompt:

```text
Сделай актуальный research для админа Telegram-бота генерации контента.
Найди новые/важные AI-модели, API и провайдеров для image/video generation.
Оцени полезность для продукта, качество, стоимость/риски, что стоит протестировать.
Отделяй проверенные факты от рекомендаций.
```

Важно:

- research не должен менять настройки бота;
- не надо автоматически подключать новые API;
- итог должен быть кратким: факты, риски, рекомендации.

## 14. Инструкция внутри бота

Добавьте экран инструкции:

```text
📘 Инструкция: ИИ-админ

Как пользоваться:
1. Откройте /admin → 🤖 ИИ-админ.
2. Напишите задачу обычным текстом.
3. Если действие меняет данные, подтвердите выполнение.

Примеры:
• сделай отчёт по боту
• проанализируй последние логи
• найди новые ИИ для генерации видео и фото
• проверь пользователя 123456789
• начисли 50 BoomCoin пользователю 123456789
• создай промокод VIP20 скидка 20 лимит 100
• очисти контекст
```

Держите инструкцию короче 4096 символов, чтобы она помещалась в одно сообщение Telegram.

## 15. Безопасность

Обязательные правила:

- Проверка `is_admin` на каждом handler.
- Allowlist действий.
- Confirmation для любых изменений.
- Нет произвольного shell/SQL от модели.
- Нет массовой рассылки через AI.
- Санитизация HTML перед отправкой в Telegram.
- Ограничение длины сообщений.
- Idempotency для финансовых операций.
- Логи читать только из разрешённых файлов.
- Не показывать секреты из `.env`, токены и API keys.

## 16. Тесты

Минимальные тесты:

```python
async def test_plans_add_credits():
    plan = await service.plan_action("начисли 50 BoomCoin пользователю 123456789")
    assert plan["action"] == "add_credits"
    assert plan["params"] == {"telegram_id": 123456789, "amount": 50}
    assert plan["requires_confirmation"] is True

async def test_plans_agent_report():
    plan = await service.plan_action("сделай отчёт по боту")
    assert [item["action"] for item in plan["actions"]] == [
        "stats",
        "maintenance_status",
        "list_promos",
        "analyze_logs",
    ]

async def test_plans_research():
    plan = await service.plan_action("найди новые ИИ в генерации контента")
    assert plan["action"] == "research_ai"
```

Также проверьте:

- кнопка `ИИ-админ` есть в админ-клавиатуре;
- не-админ не имеет доступа;
- `unknown` не выполняется;
- mutating action не выполняется без подтверждения.

## 17. Чеклист внедрения

- [ ] Добавить `admin_ai_service.py`.
- [ ] Добавить FSM states.
- [ ] Добавить кнопки `🤖 ИИ-админ` и `📘 Инструкция ИИ`.
- [ ] Добавить handlers `/admin_ai`, `admin_ai`, `admin_ai_help`, `admin_ai_confirm`, `admin_ai_cancel`.
- [ ] Реализовать validation.
- [ ] Реализовать action executor.
- [ ] Реализовать multi-step executor.
- [ ] Добавить session memory в FSM.
- [ ] Добавить анализ логов из allowlist файлов.
- [ ] Добавить research через LLM с web search.
- [ ] Добавить тесты fallback planner и safety.
- [ ] Прогнать `python -m compileall bot`.
- [ ] Прогнать `pytest`.
- [ ] Перезапустить сервис.

## 18. Примеры команд для админа

```text
сделай отчёт по боту
дай сводку по состоянию и последним ошибкам
проанализируй последние логи
найди ошибки webhook за последние 500 строк
почему могли падать генерации?
найди новые ИИ для генерации видео и фото
сравни новые image-to-image модели для фотореализма
покажи статистику
проверь пользователя 123456789
начисли 50 BoomCoin пользователю 123456789
спиши 10 BoomCoin у 123456789
забань 123456789
разбань 123456789
покажи промокоды
создай промокод VIP20 скидка 20 лимит 100
создай промокод GIFT50 BoomCoin 50 лимит 200
отключи промокод VIP20
включи техрежим
выключи техрежим
экспорт пользователей
очисти контекст
```

## 19. Что не стоит делать

- Не давать модели доступ к произвольным командам сервера.
- Не выполнять SQL, который сгенерировала модель.
- Не объединять AI planner и executor в один неразделимый слой.
- Не отправлять персональные данные во внешний LLM без необходимости.
- Не позволять AI делать рассылки по пользователям.
- Не скрывать от админа, какое действие будет выполнено.

Хорошая модель внедрения: AI думает и предлагает, backend проверяет и выполняет, админ подтверждает рискованные изменения.

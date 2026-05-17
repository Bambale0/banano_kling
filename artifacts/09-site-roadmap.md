# 2Loop Site Roadmap

Дата составления: 2026-05-16

## Цель

Сайт 2Loop должен стать не витриной, а полноценной рабочей поверхностью продукта: пользователь видит pastel grunge бренд, понимает ценность GOE, запускает AI-генерации, использует товары как референсы, возвращается в историю и при необходимости переходит в Telegram Mini App. Оператор видит заказы, задачи, пользователей, оплату и ошибки генераций без ручного поиска по логам.

## Принципы продукта

- Первый экран должен показывать реальный продукт: AI-atelier, GOE, сценарии генерации и каталог, а не абстрактный marketing hero.
- Визуальный стиль: pastel grunge, бумажная фактура, мягкие blush/ice/mint/butter тона, editorial/zine настроение, 8px radius.
- UX не должен страдать от эстетики: понятные CTA, читаемые таблицы, стабильные размеры карточек, 44px+ мобильные цели.
- Сайт и Mini App должны ощущаться одним продуктом.
- Все пользовательские данные и backend JSON отображаются безопасно.
- Любой платный или GOE-сценарий должен считать стоимость на backend.

## Текущее состояние

Готово:

- Public shell: `/`, `/dashboard`, `/creator`, `/catalog`, `/product/:article`, `/wallet`, `/history`, `/admin`.
- Pastel grunge дизайн-система для сайта и Mini App.
- Site generator через `/api/site/generate`.
- Каталог через `/api/catalog`.
- Заявки через `/api/shop/lead`.
- Admin overview через `/api/shop/admin/overview`.
- Mini App build синхронизирован в production static root.
- Landing static синхронизирован в `/var/www/2loop/static/landing`.
- Asset cache-bust: `v=20260516-grunge2`.

Ограничения:

- Нет браузерного screenshot QA в окружении без Chromium/Playwright.
- Платёжный checkout GOE на сайте пока stub/manual.
- Admin actions частично только обзорные, часть операций живёт в Telegram admin flows.
- Site demo wallet отделён от реального Telegram GOE.

## North Star

Пользователь за 60 секунд понимает:

1. Что 2Loop создаёт контент для фигурного катания.
2. Какие типы материалов можно собрать.
3. Сколько стоит генерация в GOE.
4. Где результат сохраняется.
5. Как товар из каталога превращается в контент.

## KPI

- Landing activation: доля пользователей, открывших `/creator` после первого визита.
- Generation start rate: доля посетителей `/creator`, отправивших prompt.
- Telegram handoff: клики в Mini App / bot.
- Catalog-to-content rate: клики `В сценарий` из товара.
- Lead conversion: отправки формы контактов.
- Admin usefulness: доля задач/заказов, видимых из admin overview без логов.
- Performance: LCP до 2.5s на mobile 4G, JS без runtime errors.
- Accessibility: keyboard navigation, focus states, readable contrast.

## Roadmap By Phases

### Phase 0. Stabilization And Cache Hygiene

Окно: 2026-05-16 - 2026-05-18

Цель: убедиться, что новый дизайн реально виден всем пользователям и не ломает текущие маршруты.

Задачи:

- Зафиксировать deployment checklist для landing и Mini App static sync.
- Добавить явный script/command для деплоя `static/landing` в `/var/www/2loop/static/landing`.
- Добавить явный script/command для деплоя `miniapp/dist` в `/var/www/2loop/static/miniapp`.
- Убрать ручной cache-bust из HTML в пользу переменной версии или build stamp.
- Проверить все HTML страницы на новый asset version.
- Проверить `/`, `/creator`, `/catalog`, `/wallet`, `/history`, `/admin`, `/app` через внешний URL.
- Задокументировать hard refresh и nginx cache behavior.

Acceptance:

- Внешний `https://2loop.chillcreative.ru/` отдаёт новый HTML.
- CSS/JS по новой версии возвращают `200 OK`.
- `tests/test_landing.py` зелёный.
- Mini App `/app` тянет актуальный hashed bundle.

### Phase 1. Visual QA And Responsive Polish

Окно: 2026-05-18 - 2026-05-21

Цель: довести pastel grunge дизайн до стабильного состояния на реальных viewport.

Задачи:

- Установить/подключить Playwright browser в окружении или добавить внешний screenshot workflow.
- Сделать screenshot QA для 390px, 768px, 1440px.
- Проверить hero, sidebar, mobile nav, product cards, creator composer, history cards.
- Исправить переполнения текста, особенно в KPI, таблицах и карточках каталога.
- Проверить контраст pastel элементов и focus-visible.
- Проверить отсутствие горизонтального scroll на mobile.
- Добавить visual QA report в `artifacts/08-qa-report.md`.

Acceptance:

- Есть screenshots по ключевым маршрутам.
- Нет overlap текста и controls.
- Все основные кнопки имеют 44px+ target.
- Нет отрицательного `letter-spacing` и viewport-scaled font-size.

### Phase 2. Creator UX Upgrade

Окно: 2026-05-21 - 2026-05-27

Цель: сделать `/creator` полноценным главным рабочим сценарием.

Задачи:

- Добавить понятный stepper: `1. Тип`, `2. Промпт`, `3. Стоимость`, `4. Результат`.
- Показывать стоимость выбранной генерации до отправки.
- Показывать демо/реальный тип кошелька: `site_demo`, `telegram_goe`, `auth_required`.
- Добавить states: loading, success, not enough GOE, auth required, provider unavailable.
- Добавить prompt templates для фигуристки, тренера, школы, бренда аксессуаров, SMM.
- Добавить quick insert из каталога: товар, цена, категория, описание.
- После генерации предлагать: copy, open history, create variation, send to Telegram.

Acceptance:

- Пользователь может понять стоимость до клика.
- Ошибки не выглядят как технический JSON.
- Результат безопасно отображается и копируется.
- История обновляется после успешной генерации.

### Phase 3. Catalog-To-Content Flow

Окно: 2026-05-27 - 2026-06-03

Цель: превратить каталог в источник генераций и продаж.

Задачи:

- Улучшить `/catalog`: фильтры по категории, наличию, цене, badge.
- Добавить product detail drawer без потери контекста каталога.
- Для каждого товара добавить CTA: `Пост`, `Reels`, `Карточка`, `Look`.
- Собирать prompt seed из товара на backend-safe данных.
- Добавить блок похожих товаров.
- Добавить empty states для отсутствующих фото/остатков.
- Для checkout показать server-trusted totals, delivery estimate и clear manual confirmation.

Acceptance:

- Товар можно отправить в `/creator` одним кликом.
- Checkout не доверяет клиентской цене.
- Пользователь видит актуальную цену/наличие.
- Admin может отличить товарный lead от генерации.

### Phase 4. GOE Wallet And Payment Path

Окно: 2026-06-03 - 2026-06-10

Цель: сделать GOE понятной валютой продукта и подготовить сайт к оплате.

Задачи:

- Разделить demo GOE и Telegram GOE в UI.
- Добавить объяснение GOE без обучающих простыней: цена, списание, история.
- Подключить payment session endpoint для GOE packages.
- Проверить YooKassa/Robokassa provider states.
- Добавить pending/success/fail экраны оплаты.
- Добавить idempotency для пополнений.
- Добавить webhook health indicator в admin overview.

Acceptance:

- Пользователь понимает, где demo balance, а где реальный GOE.
- Платёж нельзя подделать client-side total.
- Повторный webhook не начисляет GOE дважды.
- История транзакций обновляется после оплаты.

### Phase 5. Auth And Telegram Handoff

Окно: 2026-06-10 - 2026-06-17

Цель: связать сайт, Telegram Mini App и реальный аккаунт.

Задачи:

- Добавить Telegram handoff CTA во все ключевые места: creator, wallet, history, auth notice.
- Добавить QR/deep link для desktop пользователей.
- Определить стратегию site session -> Telegram user linking.
- Показывать benefits входа через Telegram: реальный GOE, история, покупки, admin access.
- Для Mini App улучшить auth-required экран.
- Проверить initData validation и fail-closed admin behavior.

Acceptance:

- Desktop пользователь понимает, как продолжить в Telegram.
- Mini App не показывает фейковый баланс вне Telegram.
- Admin tab виден только админам.

### Phase 6. Admin Console V1

Окно: 2026-06-17 - 2026-06-26

Цель: сделать `/admin` полезным для оператора без логов.

Задачи:

- Разделить overview на tabs: Users, Orders, Generations, Payments, Products, Webhooks.
- Добавить фильтры задач: status, provider, type, date.
- Добавить order status update UI.
- Добавить product override UI: name, price, stock, hide/show, image.
- Добавить failed generation queue.
- Добавить safe JSON drawer для raw payload.
- Добавить audit trail для admin actions.

Acceptance:

- Оператор видит последние ошибки генераций.
- Заказ можно найти и обновить статус.
- Товар можно скрыть/переименовать/обновить цену.
- Все admin endpoints защищены.

### Phase 7. Content And SEO

Окно: 2026-06-26 - 2026-07-03

Цель: привести сайт к индексируемой структуре без потери app-first UX.

Задачи:

- Разнести SEO content по страницам: для тренеров, школ, брендов, родителей фигуристов.
- Добавить FAQ блоки без перегруза интерфейса.
- Добавить structured data для products и software application.
- Обновить sitemap.
- Проверить canonical/OG/Twitter cards.
- Оптимизировать изображения и alt.
- Добавить landing copy variants для A/B тестов.

Acceptance:

- Каждая публичная страница имеет уникальный title/description.
- Product pages имеют structured data.
- Lighthouse SEO без критических ошибок.

### Phase 8. Reliability, Observability And Release Flow

Окно: 2026-07-03 - 2026-07-12

Цель: сделать выпуск сайта повторяемым и наблюдаемым.

Задачи:

- Добавить deploy script: build Mini App, run tests, sync static, verify external URL.
- Добавить smoke tests для external URLs.
- Добавить error logging для frontend API failures.
- Добавить lightweight analytics events: route view, creator start, generation success/fail, catalog seed, lead submit.
- Добавить uptime/health report для `/health`, `/api/catalog`, `/api/site/cabinet`, `/api/miniapp/health`.
- Добавить rollback procedure: previous static archive + asset version revert.

Acceptance:

- Любой релиз проходит один documented command.
- Есть rollback за 5 минут.
- External smoke подтверждает новую версию ассетов.

## Backlog

High priority:

- Visual screenshot QA.
- Deploy script for `/var/www/2loop/static`.
- Real GOE payment path.
- Creator error states.
- Telegram account linking.

Medium priority:

- Admin tabs.
- Product override UI.
- Prompt template library.
- Product-to-content variants.
- SEO content expansion.

Later:

- A/B testing.
- Personal workspaces.
- Saved brand presets.
- Team access for schools/SMM.
- Storybook or component gallery.

## Risks

- Nginx static cache can keep old UI for 30 days if asset version is not changed.
- Site demo wallet may confuse users if not visually separated from Telegram GOE.
- Pastel grunge visual style can reduce readability if contrast is not tested.
- Admin overview can expose sensitive data if drawer content is not filtered.
- Provider webhooks require strict secret configuration.

## Release Checklist

Before every release:

- Run `./venv/bin/pytest -q`.
- Run `npm --prefix miniapp run build`.
- Run `node --check static/landing/js/site.js`.
- Scan CSS for negative letter spacing and viewport-scaled font sizes.
- Build landing archive.
- Sync `static/landing/` to `/var/www/2loop/static/landing/`.
- Sync `miniapp/dist/` to `/var/www/2loop/static/miniapp/`.
- Verify external `/`, `/creator`, `/catalog`, `/wallet`, `/history`, `/app`.
- Confirm HTML references new asset version.

## Suggested Next Sprint

Sprint dates: 2026-05-18 - 2026-05-27

Sprint goal: make the new pastel grunge site visually verified and improve `/creator` enough that users can reliably generate from prompt or catalog.

Planned deliverables:

- Screenshot QA report.
- Deploy script.
- Creator stepper and states.
- Prompt templates.
- Catalog seed improvements.
- Updated QA artifact.

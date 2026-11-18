# NEUROMIX — публичный мобильный лендинг на корне домена

## Задача и исходное состояние (18.11.2026)

- Источник: Bambale0/banano_kling, только ветка `tanyapi`; baseline `4ae787db41072857f51c28968985d0183075c38f`.
- Live HTTPS vhost `/etc/nginx/sites-available/neuromixbot.com.conf` на host `tanyapi` возвращает `302 /mini-app/` для корня; существующие `/mini-app/` и `/mini-app/api/` обслуживаются отдельно.
- Telegram Login Widget и `/mini-app/api/browser-auth` существуют; email / Google / Яндекс ID пока не подключены на сервере.
- Цель: не перестраивать Mini App; сделать лёгкую красивую мобильную точку входа с настоящей палитрой из `frontend/miniapp-v0/app/globals.css`.

## Сделано в task branch

1. `web/landing/index.html`: семантическая статическая страница без внешних JS/CSS, mobile-first адаптив (включая 320px), исходные OKLCH design tokens, доступные anchor/CTA, адаптивный иллюстративный SVG, prefers-reduced-motion, social/SEO metadata.
2. Все действующие входы/CTA направлены в проверенный `/mini-app/` (имеющуюся Telegram browser auth). Почта, Google и Яндекс ID честно отмечены «скоро» и не создают ложных авторизационных состояний. Привязка профилей — будущая функция, не обещание текущей реализации.
3. `web/landing/robots.txt` / `sitemap.xml`: индексируемый только marketing root; Mini App и API исключены из robots.
4. `ops/nginx/neuromixbot.com.conf`: только exact root + SEO resources, маршруты `/mini-app/` и API сохранены.
5. `scripts/deploy_landing_local.sh`: точный release SHA, HTML-contract preflight, snapshots, atomic static copy, хирургическая правка только exact root в живом Nginx vhost с сохранением аварийного VK isolation, nginx -t, reload, smoke root + sitemap/robots + exact Mini App revision, rollback on error.
6. Hook в `scripts/deploy_miniapp_local.sh` выполняется после успешного smoke Mini App; нет отдельного несогласованного деплоя.
7. `tests/test_public_landing.py`: контракт лендинга, цвета, CTA, SEO, сохранение маршрутов и fail-safe деплоя.

## Разграничение задач

- **В объёме этого релиза:** мобильный маркетинговый сайт на `https://neuromixbot.com/` и вход через существующую веб-авторизацию Telegram.
- **Вне этого релиза:** самостоятельная email-авторизация, OIDC Google/Яндекс, identity-linking (требуют backend identity и миграционного плана; см. epic #611). Никаких фейковых Telegram ID, фиктивных OAuth-кнопок, переносов балансов и изменений платежей.

## Проверки и эксплуатация

- Preflight: `bash -n` publish script, Python HTMLParser single-H1 / CTA / palette / misleading-auth checks: OK через SentinelX scratch (не production).
- PR gate: Python regression, 4 защищённых CI-гейта и squash auto-merge только в `tanyapi`.
- Production acceptance: `GET /` → 200 и NEUROMIX landing; `GET /mini-app/` → 200; `revision.txt` точный release SHA; `GET /robots.txt`, `GET /sitemap.xml` → 200; `nginx -t`; проверить browser Telegram login отдельно.
- Rollback: nightly-owned backups `/var/backups/banano-landing/neuromixbot.com/` не удаляются; publisher сохраняет и восстанавливает исходный Nginx конфиг на сбое. Вся Mini App остаётся нетронутой.
- Risk: исходный live Nginx vhost содержит оперативные изменения и отличается от template; deploy script изменяет только один точный блок и откажется работать при неизвестном формате, без перезаписи всего vhost.

## Исправление preflight — изоляция корневого сайта

18.11.2026 выяснено на production: `/var/www/neuromixbot.com` — симлинк на `/var/www/tanyapp.xn--e1aikcel5c5a.online`, а далее на `/var/www/tanyapp.chillcreative.ru`. Развёртывание HTML в этот путь затронуло бы резервное имя. Корневой публичный лендинг теперь публикуется **только в `/var/www/neuromix-landing`**, с правами `0755`, а точные Nginx-маршруты `/`, `/robots.txt`, `/sitemap.xml` задают локальный `root` отдельно от общей Mini App. Предусмотрен отказ при симлинке на приватном каталоге. Добавлен регрессионный тест; Mini App и резервные имена остаются неизменными.

## Восстановление публичного корня и гонка Nginx reload

18.11.2026 публичный `/` восстановлен обратимым ручным hotfix через SentinelX (без изменения backend/Mini App), поскольку protected CI был заблокирован ошибкой экранирования apt fixture. Первые запросы после успешного `systemctl reload nginx` ещё возвращали `302` от прежних Nginx worker; позднее origin и Cloudflare отвечают `200`. Publisher теперь делает bounded retry по origin и Cloudflare и проверяет реальный HTML. Окончательная фиксация в релизном SHA требует PR #613 → `tanyapi` и production smoke.

## Редизайн mobile-first (запрос 18.11.2026)

Применены навыки из `Bambale0/.agents` (прочитанные `SKILL.md`): `anti-ui-slop`, `frontend-design`, `frontend-ux-audit`, `design-taste-frontend`.

**Дизайн-контракт:** корневой сайт — компактный входной портал, не второй React/Mini App. Визуальный язык *digital atelier / editorial studio*: крупная структурная типографика, асимметричная композиция с оригинальными inline-SVG иллюстрациями визуальных концептов (не выдаются за пользовательские генерации), цвета из `frontend/miniapp-v0/app/globals.css`. По умолчанию одна главная цель — перейти в уже существующую `/mini-app/` с рабочим входом через Telegram. Почта, Google и Яндекс ID показаны как недоступные до появления реальной серверной авторизации. Привязка аккаунтов отдельно от данного релиза. Обещаний цен, выдуманных пользователей, несуществующих URL и метрик нет.

**Сокращено:** предыдущая 35KB страница с повторными маркетинговыми секциями, ложным предпросмотром отдельного приложения и неуместным длинным скроллом заменена на компактный hero, узкую панель возможностей и прямой блок входа. Прямых внешних JS/шрифтов/изображений нет; PNG и ресурсы Mini App не копируются. Для безопасности старые Telegram root deep links с `tgWebAppData` / `tgWebAppStartParam` / `startapp` продолжают перенаправляться на `/mini-app/`.

**Поведение мобильного CTA:** закреплённая кнопка показывается только при уходе основного CTA за viewport; используется `IntersectionObserver` вместо scroll listeners. В невидимом состоянии ссылка имеет `inert`, `aria-hidden=true`, нулевую opacity и не участвует в keyboard navigation. При отсутствии Observer доступный основной CTA остаётся в hero. Учитываются safe-area и prefers-reduced-motion.

**Проверено на изолированном файле ветки через SentinelX host `tanyapi` (без изменения production):**

- `13/13` Python контрактных тестов `tests/test_public_landing.py`.
- `bash -n` для `deploy_landing_local.sh` и `deploy_miniapp_local.sh`.
- Chromium Playwright на 320, 360, 390, 768, 1440 px: ни одной ошибки JS и горизонтального переполнения; CTA на месте, 5 ссылок на Mini App; закреплённая кнопка появляется после прокрутки и становится inert снова при возврате наверх.
- Визуальный осмотр screenshot 390 и 1440 px.
- Никаких изменений backend, пользователей, identity, платежей, балансам, VK-маршрутам и Mini App.

**Релиз:** только PR #613 → защищённая `tanyapi` с auto-merge после четырёх обязательных CI checks → штатный production deploy → проверка root HTML, точных входов и сохранения Mini App revision. Не считать продакшен обновлённым до сверки SHA и проверок.

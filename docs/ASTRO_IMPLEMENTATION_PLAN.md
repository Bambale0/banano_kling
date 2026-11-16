# Astro в NEUROMIX — план реализации (2026-11-08)

Статус: **UI-концепт переносится в актуальную `tanyapi` отдельным PR вместо конфликтующего #434**. Полноценные расчёты и платные операции **не подключены**.

## Цель

Добавить в существующее Telegram Mini App самостоятельный раздел Astro с дизайном по двум пользовательским референсам:

1. Каталог из семи золотых карточек на космическом фоне.
2. Экран «Натальная карта» с золотым зодиакальным кругом, датой/временем/местом рождения и основной кнопкой.

Референсы показывают структуру и визуальную тему. Получение результатов должно происходить **только** после реального backend-расчёта, а не генерации правдоподобных случайных градусов.

## Аудит до реализации

- Repo: `Bambale0/banano_kling`, production-line: `tanyapi`.
- UI: `frontend/miniapp-v0`, Next.js 16 / React 19 / Tailwind 4, статический export.
- Bootstrap/identity/balance: существующие `HeroHeader`, `AppProvider` и `TabNav`; повторно не создавать.
- `tabComponents` использует числовые ID 0..7. Новый Astro = ID 8, Motion = ID 3 остаётся доступен через студию.
- В `bot/miniapp.py` нет подтверждённых Astro API; не создавать фиктивный endpoint, тариф или списание.
- Шапка и баланс работают только после успешной Telegram-авторизации; новые экраны наследуют эти ограничения.
- Два скриншота — референсы, а не готовые отдельные PNG/SVG-ассеты. В первом UI-срезе графика воссоздана в SVG/CSS; **пиксельная идентичность художественного фона потребует исходных asset-файлов или визуального сравнения на реальных устройствах**.

## Пилотная видимость: только администраторы (2026-11-09)

- Превью Astro доступно только при `state.mode === 'live' && state.user.isAdmin === true` — роль приходит из аутентифицированного backend bootstrap, не из query/localStorage.
- Обычный Telegram/VK пользователь **не видит Astro**, а нижняя навигация сохраняет прежний `Motion` (tab ID 3); администратор видит `Астро` (ID 8) в том же месте.
- `setActiveTab(8)` запрещён без подтверждённого админского статуса; `TabContent` принудительно рендерит безопасную «Студию» для обходных и устаревших tab IDs.
- Когда backend bootstrap отозвал роль, `activeTab=8` автоматически сбрасывается на «Студию».
- **Backend Astro endpoints ещё отсутствуют.** При добавлении API необходимо независимо проверять роль и доступность фичи сервером: скрытая клиентская вкладка не является защитой данных/операций.
- Unit и E2E фиксируют обычного пользователя, администратора, locked-state, прямой tab ID и VK/Telegram интерфейсы.
- Публичное включение после MVP — только отдельным feature-flag через авторизованную конфигурацию и отдельным релизом, а не изменением фронтенд-константы без backend gate.

## Текущий UI-срез

- `components/tabs/astro-tab.tsx`: каталог семи функций, локальная навигация, общие поля рождения, формы для совместимости, выбранного года и лунного календаря.
- `components/tabs/astro-tab.css`: локальные цвета, звёздный фон, золотые контуры, карточки, зодиакальный круг, адаптивная форма, safe viewport.
- `components/tab-nav.tsx`: Astro вместо Motion **только в нижней панели**; Motion-путь через Studio не изменяется.
- `components/tab-content.tsx`: новый lazy tab ID 8.
- `components/tabs/astro-tab.test.tsx`: базовая UI-навигация и проверки ввода.
- Даты, место и время не сохраняются и не отправляются. Результатов и списаний пока нет. Текст прямо сообщает, что расчёт не подключён.

## Дальнейшие вертикальные срезы

### 1. Дизайн / пользовательский сценарий

1. Снять Playwright-скриншоты 390x844 и 414x896 на эмуляции iPhone, также Android и desktop.
2. Сравнить с концептом: top/bottom insets, шапка, расстояния, 7 карточек, золото/контуры, центральный зодиак, поля, клавиатура, скролл.
3. Заменить декоративные SVG на экспортированные исходные художественные иллюстрации, если их предоставит автор; хранить оптимизированные webp/avif локально, не загружать сторонние картинки.
4. Проверить скролл при открытой клавиатуре, 320px ширину, iOS Safari, Telegram WebView, safe area и accessibility.
5. По UX добавить возврат из результатов, skeleton, empty/error states и истечение формы без потери введённых значений при штатной навигации.

### 2. Профили рождения и геокодинг

Предлагаемый, **не существующий пока** контракт:

- `GET /mini-app/api/astro/places?q=...` — поиск города, страна, выбранная IANA timezone и координаты; rate limit, кэш, timeout.
- `GET /mini-app/api/astro/profiles` / `POST /mini-app/api/astro/profiles` — только свои профили, opt-in persistence.
- `DELETE /mini-app/api/astro/profiles/{id}` — удаление профиля и производных персональных данных.

Хранить дату и локальное время отдельно от UTC, IANA timezone, координат и `time_precision` (точное, приблизительное, неизвестно). Рассчитывать исторический UTC offset по зоне и дате, не использовать текущий offset города. Невозможные и неоднозначные местные времена (DST gap/overlap) требуют отдельного UI-выбора/сообщения. Профили партнёров — только по согласию и с теми же правами на удаление.

### 3. Астрономическое ядро

Выбрать лицензируемую эфемериду до запуска публичного сервиса. Swiss Ephemeris предлагает AGPL или коммерческую лицензию; для закрытого коммерческого backend нельзя автоматически считать его бесплатным без проверки соблюдения условий. Возможна альтернатива через разрешённый API/другую библиотеку.

Один детерминированный модуль `astro_engine`:

- вход: локальное рождение + timezone + latitude/longitude + явная точность времени;
- нормализация в UTC, юлианская дата, положения планет, долготы, знаки, аспекты и орбисы;
- дома, ASC/MC только при достаточно точном времени; система домов через управляемую конфигурацию;
- при высоких широтах — протестированная альтернатива для систем домов, не «тихий» некорректный результат;
- версионирование расчёта, эфемерид и настроек;
- output JSON с точными координатами и evidence, не текстовая догадка LLM.

Астрологическая интерпретация относится к развлечениям; не заявлять о доказанном предсказании судьбы или медицинских/финансовых фактах.

### 4. Семь сервисов

| Функция | Вход | Выход |
| --- | --- | --- |
| Натальная карта | 1 профиль | круг планет, дома/аспекты, текст |
| Совместимость | 2 профиля | синастрические аспекты и интерпретация |
| Кармический разбор | 1 профиль | лунные узлы, Сатурн, интерпретация |
| Годовой прогноз | профиль + год | транзиты и периоды |
| Гороскоп на месяц | профиль + месяц | месячные транзиты |
| Соляр | профиль + год + **место проживания на соляр** | момент возвращения Солнца и локальная карта |
| Лунный календарь | месяц + timezone | фазы, события, календарные даты |

Не строить соляр исключительно по месту рождения: местонахождение на момент соляра влияет на карту домов. Время рождения неизвестно => показывать только допустимые по точности результаты.

### 5. Сервис интерпретации, история и тарификация

- Детерминированные расчёты отдельно от LLM. LLM получает **только структурированный расчёт**, шаблон из управляемых админом промптов, не может менять градусы/дома/аспекты.
- Версионированный результат, повторный просмотр без повторной оплаты и без повторного provider-запроса.
- Цены, флаги доступности, лимиты, системные промпты и модель — из существующей runtime/admin-конфигурации, **не hardcode**. До выбора тарифов функционал не выполняет списаний.
- Оплата атомарна с записью заказа и idempotency key; повтор webhook, потеря ответа, timeout, недоступность интерпретатора, возвраты и reconciliation — отдельные тесты. Кэш расчёта нельзя использовать для обхода чужого доступа.
- Не логировать даты рождения, города и персональные интерпретации; логировать `request_id`, user ID, service ID, duration, calc version, outcome, billing receipt.

### 6. Релизные gates

1. Frontend: unit + lint + typecheck + Next static production build.
2. E2E: меню, 7 переходов, форма/валидация, табы, клавиатура и безопасный возврат; браузер + Telegram WebView.
3. Backend: unit на известные эфемеридные примеры, timezone/DST/полюса, API auth/isolation, rate-limit.
4. Billing: идемпотентность и компенсация ошибок; никаких невидимых списаний.
5. Закрытый feature flag; админ-тест без реальных юзерских списаний.
6. PR в `tanyapi`, обязательный CI, native auto-merge после успешного gate, exact-SHA production deploy, health, screenshot smoke, observability.
7. Rollback: флаг Astro off; UI revert без миграции для первого среза. Для будущих таблиц — только обратимые миграции.

## Не делаем на UI-этапе

- не придумываем геокодинг, предсказания и цены;
- не принимаем внешнюю LLM-генерацию за вычисленную карту;
- не добавляем ключи и сторонние SDK в frontend;
- не меняем существующие финансовые и генерационные маршруты;
- не называем feature production-ready до screenshot + CI + production smoke.


## Astro lunar factual calculation pilot (#544, 2026-11-16)

- New isolated lunar calculation module `bot/services/astro_lunar.py`, MIT Astronomy Engine 2.1.19.
- Server endpoint `POST /mini-app/api/astro/lunar` accepts authenticated Telegram `init_data`, `period` in YYYY-MM and an explicit IANA `timezone`. Every request checks `config.is_admin` server-side; VK session refused.
- Versioned response contains each date's Moon longitude/sign/illumination/phase at local noon and exact quarter-event instants in UTC and local time. Synodic day counts complete 24-hour UTC intervals since exact new moon; it is **not** the traditional day counted by moonrise.
- No birth data stored, no payments, no fake aspects/void-of-course/eclipses/traditional advice. Reusable calendar results do not use any LLM.
- These changes **do not complete** natal/synastry/karma/year/month/solar interpretation, long reports, saved history, geocoding or billing. Do not represent the seven-service project as complete until #544 acceptance passes for all seven.
- Await CI and verified exact-SHA deploy; keep admin-only gate.


## Натальная карта: только проверяемые исходные астрономические факты (2026-11-16)

- `POST /mini-app/api/astro/natal` — новый Telegram admin-only endpoint. На каждом обращении сервер валидирует подписанный `init_data` и текущую роль `config.is_admin`; VK-сессия не подходит.
- Ввод: `date=ДД.ММ.ГГГГ`, `time=ЧЧ:ММ` (может отсутствовать), `timezone` как историческая IANA zone, необязательный `fold=0|1` при неоднозначном местном времени. Время DST gap отвергается; для fold нужен явный выбор. Произвольное название города НЕ считается координатами.
- `astro.natal.facts.v1` — долготы Солнца, Луны и восьми планет в тропической геоцентрической ECT системе; знак, градус в знаке, приближённое суточное движение, ретроградность и основные аспекты с орбисами из `data/astro_settings.json`.
- При неизвестном времени ставим опорную точку на местный полдень **как приближение**, не рассчитываем Луну или аспекты. Дома, ASC/MC, Лилит, узлы, Хирон и астероиды пока не рассчитаны; не выдавать этот срез за полную натальную карту.
- Не использовать LLM для выдумывания градусов. Сервис не пишет дату, город, время рождения в логи и БД; ничего не списывает. Длинные интерпретации и все остальные услуги остаются в #544.
- Тесты: реальный момент равноденствия, DST overlap/gap, високосный год, неизвестное время, орбисы и замыкание 360°, серверное разграничение ролей, 400/403/503 и фронтенд-мок выдачи результатов.


## Two-person compatibility factual calculation (#544, 2026-11-16)

- This slice ports #549 onto the already merged natal #550; only current `tanyapi` is targeted. Adds `bot/services/astro_synastry.py` and `POST /mini-app/api/astro/compatibility`.
- Reuses deterministic MIT astronomy-engine natal calculations for each person's date, time, and independently provided IANA timezone. Checks signed Telegram actor and current admin privilege on **every** request; denies VK and stale roles.
- Returns actual interchart geocentric longitude major aspects, degree separations/orbs from the same `data/astro_settings.json` policy as natal. Persons are never conflated and may have their own DST fold.
- Unknown birth time suppresses that person's Moon, marks cross-aspects approximate, and does not invent ASC, MC, house overlays, composites or compatibility scores. Input cities are currently labels only, not geo-resolved or sent to the backend.
- Mini App shows real interchart aspect facts and warns when interpretation is not yet implemented. No charges, account changes, birth-data persistence or paid LLM.
- Tests cover cross-chart wraparound, non-overlapping pairs, unknown time, role revocation/VK denial, form input separation, real UI result, browser E2E.
- #544 remains open: historical coordinates, Placidus houses, nodal/Chiron/Lilith, extensive personal interpretations, all forecast techniques, persistence, rate limits and billing approval remain outstanding.

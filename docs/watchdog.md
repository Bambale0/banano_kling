# Watchdog

## Автоперезапуск при изменениях

Для автоматического перезапуска после правок кода или `.env` используется:

- `scripts/code_reload_watchdog.py`;
- `bot-reloader.service`.

Watcher следит за:

- `.env`;
- `requirements.txt`;
- `data/price.json`;
- `bot.service`;
- файлами `*.py`, `*.json`, `*.yaml`, `*.yml`, `*.sh`, `*.service` в `bot/`, `tbank_payment/`, `scripts/`.

После изменения watcher ждёт небольшой debounce и выполняет:

```bash
systemctl restart bot.service
```

Он не делает health-check каждую минуту и не использует timer.

## Ручный health watchdog

`scripts/bot_watchdog.py` оставлен как ручная production-проверка бота:

- состояние `bot.service`;
- количество процессов `python -m bot.main`;
- доступность порта `8443`;
- ответ `/health`;
- размер `static/uploads`, логов и свободное место;
- свежие ошибки в `logs/bot.log`.

При критичной проблеме ручной watchdog один раз выполняет:

```bash
systemctl restart bot.service
```

## Установка systemd units

```bash
sudo ./scripts/install_systemd_watchdog.sh
```

Скрипт устанавливает:

- `bot.service` — foreground-запуск бота через `scripts/run_bot_foreground.sh`;
- `bot-reloader.service` — автоперезапуск при изменении кода или `.env`;
- `bot-watchdog.service` — ручная одноразовая health-проверка.

## Ручные команды

```bash
python scripts/code_reload_watchdog.py --self-test
python scripts/bot_watchdog.py --self-test
python scripts/bot_watchdog.py --no-restart
systemctl status bot.service
systemctl status bot-reloader.service
journalctl -u bot-reloader.service -n 100 --no-pager
tail -f logs/code_reload_watchdog.log
```

## Настройки

Code reloader можно переопределить переменными окружения в systemd unit:

```env
BOT_PROJECT_DIR=/root/bot/banano_kling
BOT_SERVICE_NAME=bot.service
BOT_RELOAD_POLL_SECONDS=1.0
BOT_RELOAD_DEBOUNCE_SECONDS=2.0
```

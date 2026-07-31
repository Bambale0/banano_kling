# Автоматическая установка отдельного Mini App frontend

Скрипт устанавливает на чистый Ubuntu-сервер:

- Nginx;
- Node.js 22;
- Certbot и TLS;
- UFW;
- исходники ветки `tanyapi`;
- production static export Mini App;
- проксирование `/mini-app/api/`, `/api/v1/`, `/uploads/` на отдельный backend;
- immutable cache для hashed chunks и no-store для HTML;
- резервное копирование текущей сборки;
- smoke-проверки HTML, assets, TLS и backend auth boundary.

## 1. DNS

Создайте A-запись нового домена на IPv4 frontend-сервера. Скрипт не выпустит сертификат, пока DNS не указывает на этот сервер.

## 2. Конфигурация

```bash
cp deploy/miniapp-frontend.env.example /root/miniapp-frontend.env
nano /root/miniapp-frontend.env
chmod 600 /root/miniapp-frontend.env
```

Минимум:

```dotenv
FRONTEND_DOMAIN=app.example.ru
BACKEND_ORIGIN=https://api.example.ru
CERTBOT_EMAIL=admin@example.ru
```

Если репозиторий закрытый, заранее добавьте на сервер read-only GitHub deploy key и задайте:

```dotenv
REPO_URL=git@github.com:Bambale0/banano_kling.git
```

Пароль или GitHub token в конфигурационный файл не помещается.

Для backend на открытом aiohttp-порту:

```dotenv
BACKEND_ORIGIN=http://203.0.113.10:1888
BACKEND_HOST_HEADER=api.example.ru
```

## 3. Первая установка

```bash
sudo bash scripts/install_miniapp_frontend_host.sh \
  --config /root/miniapp-frontend.env \
  --install
```

## 4. Последующие обновления

```bash
sudo bash /opt/banano-kling-src/scripts/install_miniapp_frontend_host.sh \
  --config /root/miniapp-frontend.env \
  --deploy-only
```

Обновление выполняет `git fetch`, жёстко синхронизирует checkout с `origin/tanyapi`, выполняет `npm ci`, lint, production build и копирует `out/` без `--delete`. Старые hashed chunks остаются доступны закешированным Telegram WebView.

## 5. Автонастройка backend

Если frontend-сервер имеет SSH-ключ для backend, добавьте:

```dotenv
BACKEND_SSH_HOST=root@203.0.113.10
BACKEND_ENV_FILE=/root/tanya/banano_kling/.env
BACKEND_SERVICE=banano-kling.service
BACKEND_PORT=1888
```

Тогда скрипт:

- сохранит backup `.env`;
- установит `MINI_APP_URL=https://FRONTEND_DOMAIN/mini-app/`;
- установит `WEBHOOK_BIND_HOST=0.0.0.0`;
- при наличии UFW разрешит backend-порт только с IP frontend-сервера;
- перезапустит `banano-kling.service`;
- проверит backend `/health`.

SSH-пароль в config не записывается. Используется заранее установленный ключ.

## 6. Проверки

После успешной установки:

```bash
curl -fsSI https://app.example.ru/mini-app/
curl -fsS https://app.example.ru/frontend-health
curl -i -X POST https://app.example.ru/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' --data '{}'
```

Последний запрос должен вернуть отказ авторизации `400`, `401` или `403`, а не `404`/`502`.

## 7. Откат

Перед каждым обновлением создаётся hard-link backup в:

```text
/var/backups/banano-miniapp/DOMAIN/YYYYMMDD-HHMMSS
```

Для отката:

```bash
sudo rsync -a --delete \
  /var/backups/banano-miniapp/DOMAIN/BACKUP/ \
  /var/www/DOMAIN/mini-app/
sudo nginx -t && sudo systemctl reload nginx
```

`--delete` допустим именно при осознанном rollback на целостную сохранённую сборку. В обычном deploy скрипт его не применяет.

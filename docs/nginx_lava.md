# LAVA Nginx — историческая инструкция, не текущий production-конфиг

> **Статус: архивный материал.** Прежняя инструкция ссылалась на `nginx/lava.conf`, которого нет среди tracked-файлов, и предлагала `127.0.0.1:8443`. В рабочем NEUROMIX backend находится в Docker за Nginx на localhost port `1888`. **Не копировать конфиг, не создавать новый vhost, не запускать certbot или reload Nginx по старой инструкции.**

Для фактического webhook path, HMAC/signature, заголовков proxy и текущего порта проверьте `bot/miniapp.py` / `bot/main.py`, активный Nginx config и [production-deployment.md](production-deployment.md). Развёртывание только через защищённый PR в `tanyapi` и штатный CI/CD, инфраструктурные изменения — с отдельным review.

Этот документ сохранён как след исторической попытки настройки, **не** как runbook. Актуальные инструкции — [runbook.md](runbook.md) и [troubleshooting.md](troubleshooting.md).

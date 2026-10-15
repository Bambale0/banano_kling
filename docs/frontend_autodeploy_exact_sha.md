# Историческая схема exact-SHA на отдельном CDN — legacy reference

> **НЕ текущий production release.** Старые профили `cdn.chillcreative.ru`, `91.200.84.187` и `/opt/banano-kling-src` описывают отдельный frontend-хост прошлой инфраструктуры. Сейчас static Mini App расположен на `tanyapp.xn--e1aikcel5c5a.online` вместе с backend на `144.76.188.75`, выпускается через protected `tanyapi` CI/CD. Ниже сохранены старые команды как история; не применять к production без отдельного согласования. См. [production_auto_deploy.md](production_auto_deploy.md) и [runbook.md](runbook.md).


The production frontend workflow validates a commit on GitHub-hosted runners first
and falls back to the self-hosted `nuromix` runner only for trusted pushes.

The remote deployment must publish the exact commit that passed CI. It therefore:

1. resets `/opt/banano-kling-src` to `GITHUB_SHA`;
2. invokes `scripts/install_miniapp_frontend_https_host.sh` directly instead of
   `cdn.sh`, because `cdn.sh` refreshes `origin/tanyapi` internally;
3. verifies that the checkout SHA did not change during deployment;
4. compares the built `out/index.html` with the deployed `index.html`;
5. checks the public health endpoint and Mini App HTTP response.

This prevents a newer untested commit from being picked up between CI completion
and the remote frontend build.

# Frontend auto-deploy verification checklist

- GitHub-hosted frontend checks pass, or trusted push falls back to `nuromix`.
- Full Python/Docker CI for the same SHA is green.
- Frontend SSH secrets are complete and host key is pinned.
- `/opt/banano-kling-src` has no tracked or untracked local changes.
- `/etc/banano-miniapp/profiles/cdn.chillcreative.ru.env` exists.
- The installer deploys the exact `GITHUB_SHA`.
- Source and deployed `index.html` files match byte-for-byte.
- `https://cdn.chillcreative.ru/frontend-health` responds successfully.
- `https://cdn.chillcreative.ru/mini-app/` responds with HTTP 200.

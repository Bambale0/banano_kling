# NEUROMIX Mini App frontend deployment

## Production topology

| Component | Value |
| --- | --- |
| Public URL | `https://neuromixbot.com/mini-app/` |
| Production host | `144.76.188.75` (shared with backend) |
| Static root | `/var/www/neuromixbot.com/mini-app` |
| Source branch | `tanyapi` |
| API origin | `https://tanyapi.chillcreative.ru` |
| Release workflow | `.github/workflows/deploy-production.yml` |
| Publisher | `scripts/deploy_miniapp_local.sh` |

The Mini App is served directly from the production host. Its page and
`/mini-app/api/*` use the `neuromixbot.com` origin; Nginx forwards API requests
to the backend. There is no separate CDN/frontend host in the current launch
or deployment path.

## Release path

Normal production releases go through a task PR to `tanyapi`. After merge,
`deploy-production.yml` runs `scripts/deploy_miniapp_local.sh` for the exact
release SHA and verifies that `/mini-app/revision.txt` matches it. The publisher
builds the static export, preserves existing hashed assets for open Telegram
WebViews, backs up the current release, and validates the live HTML and assets.

Do not use the legacy separate-host remote deployment workflow for the Mini
App. Do not manually reset or deploy the production checkout as part of an
ordinary release.

## Local frontend checks

```bash
cd frontend/miniapp-v0
npm ci
npm run lint
npm test
npm run build

test -s out/index.html
test -d out/_next/static
```

The build is a static export; production does not run a frontend Node.js
server. `bot/miniapp.py` is the source of truth for API contracts.

## Production smoke checks

```bash
curl -fsSI https://neuromixbot.com/mini-app/
curl -fsS https://neuromixbot.com/mini-app/revision.txt
curl -fsS https://neuromixbot.com/mini-app/ \
  | grep -o '<title>[^<]*</title>'
```

Every JavaScript and CSS URL in the HTML must return `200`:

```bash
curl -fsS https://neuromixbot.com/mini-app/ \
  | grep -oE '/mini-app/_next/static/[^" ]+\.(js|css)' \
  | sort -u
```

The unauthenticated API boundary should return an auth response, not a proxy
failure:

```bash
curl -i -X POST \
  https://neuromixbot.com/mini-app/api/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{}'
```

An auth `401` outside Telegram is expected: the request has no Telegram
`initData`. A `502`/`504`, failed TLS handshake, missing current asset, or a
revision mismatch is an infrastructure/deployment failure.

## Browser and cache behavior

- HTML must be `no-store`/`no-cache`.
- Hashed `_next/static` assets may be immutable.
- Keep older hashed assets available for in-flight Telegram WebViews.
- The shell shows its loader until Telegram auth/bootstrap finishes; a browser
  without Telegram auth may show the Telegram-open gate.

After a frontend release, fully close and reopen the Mini App in Telegram.
Verify the loader, successful bootstrap, navigation, history, uploads, and
media previews on the affected client.

Legacy media URL normalization is separate from the Mini App launch host and
remains in place for backward compatibility with stored media records. Do not
use legacy media URLs as the app's public URL.

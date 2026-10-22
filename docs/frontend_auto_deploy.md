# NEUROMIX frontend auto deploy

Production releases use `tanyapi` and `.github/workflows/deploy-production-reliable.yml`
(with `.github/workflows/deploy-production.yml` as fallback). Both wait for exact-SHA
CI and invoke `scripts/deploy_miniapp_local.sh` on the backend host, 144.76.188.75.

The script builds the static export, preserves historical assets/backups, publishes
`/var/www/neuromixbot.com/mini-app`, and checks the public revision and JavaScript
assets at `https://neuromixbot.com/mini-app/`. `MINIAPP_FRONTEND_DOMAIN` can override
the frontend domain; the optional root-only profile is
`/etc/banano-miniapp/profiles/<domain>.env`. This script does not manage DNS or TLS.

`/var/www/neuromixbot.com` shares the existing static root with
`/var/www/tanyapp.xn--e1aikcel5c5a.online`; historical launch pages redirect to the new domain, while old assets/API/media
continue to serve the same release. The Nginx vhost is recorded in `ops/nginx/neuromixbot.com.conf`.

The standalone 91.200.84.187 host and `cdn.sh` domain installer are legacy paths.
Do not run them for normal production releases. See [production-deployment.md](production-deployment.md)
for the current infrastructure, TLS renewal and verification commands.

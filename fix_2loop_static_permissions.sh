#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="${TWOLOOP_DOMAIN:-2loop.chillcreative.ru}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATIC_SRC="$PROJECT_ROOT/static"
PUBLIC_ROOT="${TWOLOOP_PUBLIC_ROOT:-/var/www/2loop}"
NGINX_AVAILABLE="/etc/nginx/sites-available/$DOMAIN"
NGINX_ENABLED="/etc/nginx/sites-enabled/$DOMAIN"
BACKEND_PORT="${TWOLOOP_BACKEND_PORT:-8444}"

log() { printf '\033[1;36m[2loop-static]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[2loop-static][error]\033[0m %s\n' "$*"; exit 1; }

if [[ $EUID -ne 0 ]]; then
  fail "Run as root: sudo ./fix_2loop_static_permissions.sh"
fi

[[ -d "$STATIC_SRC/miniapp" ]] || fail "Missing $STATIC_SRC/miniapp. Run setup_2loop_miniapp.sh first."
command -v nginx >/dev/null 2>&1 || fail "nginx not found"

log "Copying static files from $STATIC_SRC to $PUBLIC_ROOT/static"
mkdir -p "$PUBLIC_ROOT"
rm -rf "$PUBLIC_ROOT/static"
mkdir -p "$PUBLIC_ROOT/static"
cp -a "$STATIC_SRC/." "$PUBLIC_ROOT/static/"

log "Fixing ownership and permissions"
chown -R www-data:www-data "$PUBLIC_ROOT"
find "$PUBLIC_ROOT" -type d -exec chmod 755 {} \;
find "$PUBLIC_ROOT" -type f -exec chmod 644 {} \;

log "Writing nginx config with public root outside /root"
cat > "$NGINX_AVAILABLE" <<NGINX
server {
    server_name $DOMAIN;

    client_max_body_size 64M;

    location = /webhook {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/webhook;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /webhook/ {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/webhook/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /yookassa/webhook {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/yookassa/webhook;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /robokassa/ {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/robokassa/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /api/miniapp/ {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/api/miniapp/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        alias $PUBLIC_ROOT/static/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
    }

    location / {
        root $PUBLIC_ROOT/static/miniapp;
        try_files \$uri \$uri/ /index.html;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if (\$host = $DOMAIN) {
        return 301 https://\$host\$request_uri;
    }

    listen 80;
    server_name $DOMAIN;
    return 404;
}
NGINX

ln -sfn "$NGINX_AVAILABLE" "$NGINX_ENABLED"
nginx -t
systemctl reload nginx || service nginx reload

log "Testing frontend"
curl -k -I "https://$DOMAIN/" || true
log "Testing API"
curl -k "https://$DOMAIN/api/miniapp/health" || true

log "Done. Mini App static is now served from $PUBLIC_ROOT/static/miniapp"

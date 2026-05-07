#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="2loop.chillcreative.ru"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_AVAILABLE="/etc/nginx/sites-available/$DOMAIN"
NGINX_ENABLED="/etc/nginx/sites-enabled/$DOMAIN"
BACKEND_PORT="${TWOLOOP_BACKEND_PORT:-8444}"

log() { printf '\033[1;36m[2loop-nginx]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[2loop-nginx][error]\033[0m %s\n' "$*"; exit 1; }

if [[ $EUID -ne 0 ]]; then
  fail "Run as root: sudo ./fix_2loop_nginx_8444.sh"
fi

command -v nginx >/dev/null 2>&1 || fail "nginx not found"

log "Writing nginx config for $DOMAIN -> backend 127.0.0.1:$BACKEND_PORT"

cat > "$NGINX_AVAILABLE" <<NGINX
server {
    server_name $DOMAIN;

    client_max_body_size 64M;

    # Telegram webhook
    location = /webhook {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/webhook;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # AI/Kie/Kling/Replicate webhooks
    location /webhook/ {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/webhook/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # YooKassa
    location /yookassa/webhook {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/yookassa/webhook;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Robokassa
    location /robokassa/ {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/robokassa/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Mini App API
    location /api/miniapp/ {
        proxy_pass http://127.0.0.1:$BACKEND_PORT/api/miniapp/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Static uploads/assets
    location /static/ {
        alias $PROJECT_ROOT/static/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
    }

    # Mini App frontend
    location / {
        root $PROJECT_ROOT/static/miniapp;
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

log "Done. Test: curl -i https://$DOMAIN/api/miniapp/health"
log "Also verify bot webhook: curl -i https://$DOMAIN/webhook should NOT return miniapp HTML"

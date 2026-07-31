#!/usr/bin/env python3
from pathlib import Path

PATH = Path("cdn.sh")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            return text
        raise SystemExit(f"Marker not found: {old!r}")
    if count != 1:
        raise SystemExit(f"Ambiguous marker ({count}): {old!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'PROFILES_DIR="${STATE_DIR}/profiles"\nACTIVE_FILE=',
        'PROFILES_DIR="${STATE_DIR}/profiles"\nREMOTES_DIR="${STATE_DIR}/remotes"\nACTIVE_FILE=',
    )
    text = replace_once(
        text,
        '  install -d -m 0700 "$STATE_DIR" "$PROFILES_DIR"\n',
        '  install -d -m 0700 "$STATE_DIR" "$PROFILES_DIR" "$REMOTES_DIR"\n',
    )

    remote_functions = r'''
remote_profile_path() {
  printf '%s/%s.env' "$REMOTES_DIR" "$1"
}

normalize_remote_name() {
  local value="${1,,}"
  value="${value// /-}"
  value="$(printf '%s' "$value" | tr -cd 'a-z0-9._-')"
  printf '%s' "$value"
}

list_remote_names() {
  find "$REMOTES_DIR" -maxdepth 1 -type f -name '*.env' -printf '%f\n' 2>/dev/null \
    | sed 's/\.env$//' \
    | sort
}

select_remote() {
  local title="${1:-Выбери удалённый frontend}"
  mapfile -t remotes < <(list_remote_names)
  (( ${#remotes[@]} > 0 )) || return 1

  echo "$title" >&2
  local i
  for i in "${!remotes[@]}"; do
    printf '  %d) %s\n' "$((i + 1))" "${remotes[$i]}" >&2
  done

  local choice
  read -r -p "Номер: " choice || true
  [[ "$choice" =~ ^[0-9]+$ ]] || return 1
  (( choice >= 1 && choice <= ${#remotes[@]} )) || return 1
  printf '%s' "${remotes[$((choice - 1))]}"
}

source_remote_profile() {
  local name="$1"
  local file
  file="$(remote_profile_path "$name")"
  [[ -f "$file" ]] || die "Удалённый профиль не найден: $file"
  # shellcheck disable=SC1090
  source "$file"
}

remote_ssh() {
  local target="$1"
  shift
  ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=15 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    "$target" "$@"
}

configure_remote_frontend() {
  local name ssh_host source_dir domain branch use_sudo file

  name="$(normalize_remote_name "$(ask 'Имя удалённого frontend' 'tanyafrontend')")"
  [[ -n "$name" ]] || die "Имя профиля пустое"
  ssh_host="$(ask 'SSH frontend-сервера' 'root@91.200.84.187')"
  [[ -n "$ssh_host" ]] || die "SSH frontend-сервера не указан"
  source_dir="$(ask 'Каталог репозитория на frontend-сервере' "$DEFAULT_SOURCE_DIR")"

  while true; do
    domain="$(normalize_domain "$(ask 'Домен frontend' 'cdn.chillcreative.ru')")"
    validate_domain "$domain" && break
    warn "Некорректный домен"
  done

  branch="$(ask 'Ветка для выкладки' "$DEFAULT_BRANCH")"
  use_sudo=0
  confirm "SSH-пользователю нужен sudo без пароля?" "n" && use_sudo=1

  info "Проверяю SSH и сохранённый профиль домена..."
  remote_ssh "$ssh_host" \
    "SOURCE_DIR=$(printf '%q' "$source_dir") DOMAIN=$(printf '%q' "$domain") bash -s" <<'REMOTE'
set -Eeuo pipefail
test -d "$SOURCE_DIR/.git"
test -f "/etc/banano-miniapp/profiles/${DOMAIN}.env"
printf 'REMOTE_OK\n'
REMOTE

  file="$(remote_profile_path "$name")"
  {
    printf '# Managed by cdn.sh remote frontend manager\n'
    printf 'REMOTE_NAME=%q\n' "$name"
    printf 'REMOTE_SSH_HOST=%q\n' "$ssh_host"
    printf 'REMOTE_SOURCE_DIR=%q\n' "$source_dir"
    printf 'REMOTE_DOMAIN=%q\n' "$domain"
    printf 'REMOTE_BRANCH=%q\n' "$branch"
    printf 'REMOTE_USE_SUDO=%q\n' "$use_sudo"
  } > "$file"
  chmod 0600 "$file"
  success "Удалённый frontend сохранён: ${name}"
}

remote_deploy_by_name() {
  local name="$1"
  source_remote_profile "$name"

  [[ -n "${REMOTE_SSH_HOST:-}" ]] || die "REMOTE_SSH_HOST не задан"
  [[ -n "${REMOTE_SOURCE_DIR:-}" ]] || die "REMOTE_SOURCE_DIR не задан"
  [[ -n "${REMOTE_DOMAIN:-}" ]] || die "REMOTE_DOMAIN не задан"
  [[ -n "${REMOTE_BRANCH:-}" ]] || REMOTE_BRANCH="$DEFAULT_BRANCH"
  [[ "${REMOTE_USE_SUDO:-0}" =~ ^[01]$ ]] || die "REMOTE_USE_SUDO должен быть 0 или 1"

  log "Удалённая выкладка ${REMOTE_DOMAIN} через ${REMOTE_SSH_HOST}"
  remote_ssh "$REMOTE_SSH_HOST" \
    "SOURCE_DIR=$(printf '%q' "$REMOTE_SOURCE_DIR") BRANCH=$(printf '%q' "$REMOTE_BRANCH") DOMAIN=$(printf '%q' "$REMOTE_DOMAIN") USE_SUDO=$(printf '%q' "$REMOTE_USE_SUDO") bash -s" <<'REMOTE'
set -Eeuo pipefail
IFS=$'\n\t'

command -v git >/dev/null
command -v curl >/dev/null
command -v bash >/dev/null
[[ -d "$SOURCE_DIR/.git" ]]
[[ -f "/etc/banano-miniapp/profiles/${DOMAIN}.env" ]]

if [[ -n "$(git -C "$SOURCE_DIR" status --porcelain)" ]]; then
  echo "ERROR: в $SOURCE_DIR есть локальные изменения" >&2
  git -C "$SOURCE_DIR" status --short >&2
  exit 2
fi

git -C "$SOURCE_DIR" fetch --prune origin "$BRANCH"
git -C "$SOURCE_DIR" switch "$BRANCH"
git -C "$SOURCE_DIR" reset --hard "origin/${BRANCH}"

[[ -f "$SOURCE_DIR/cdn.sh" ]]
if [[ "$USE_SUDO" == "1" ]]; then
  sudo -n bash "$SOURCE_DIR/cdn.sh" --deploy-domain "$DOMAIN"
else
  [[ "$EUID" -eq 0 ]] || {
    echo "ERROR: удалённый SSH-пользователь не root. Включи REMOTE_USE_SUDO=1." >&2
    exit 3
  }
  bash "$SOURCE_DIR/cdn.sh" --deploy-domain "$DOMAIN"
fi

curl -fsS --max-time 20 "https://${DOMAIN}/frontend-health" >/dev/null
curl -fsSI --max-time 20 "https://${DOMAIN}/mini-app/" >/dev/null
printf 'REMOTE_DEPLOY_OK %s %s\n' "$DOMAIN" "$(git -C "$SOURCE_DIR" rev-parse --short HEAD)"
REMOTE

  success "Удалённый frontend ${REMOTE_DOMAIN} обновлён"
}

remote_update_interactive() {
  local name
  name="$(select_remote 'Какой удалённый frontend обновить?')" || die "Удалённый frontend не выбран"
  remote_deploy_by_name "$name"
}

remote_status_by_name() {
  local name="$1"
  source_remote_profile "$name"

  remote_ssh "$REMOTE_SSH_HOST" \
    "SOURCE_DIR=$(printf '%q' "$REMOTE_SOURCE_DIR") DOMAIN=$(printf '%q' "$REMOTE_DOMAIN") bash -s" <<'REMOTE'
set -Eeuo pipefail
printf 'host=%s\n' "$(hostname)"
printf 'domain=%s\n' "$DOMAIN"
printf 'commit=%s\n' "$(git -C "$SOURCE_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf 'branch=%s\n' "$(git -C "$SOURCE_DIR" branch --show-current 2>/dev/null || echo unknown)"
printf 'profile=%s\n' "$([[ -f "/etc/banano-miniapp/profiles/${DOMAIN}.env" ]] && echo ok || echo missing)"
printf 'nginx=%s\n' "$(systemctl is-active nginx 2>/dev/null || true)"
printf 'health=%s\n' "$(curl -fsS --max-time 10 "https://${DOMAIN}/frontend-health" 2>/dev/null || echo failed)"
printf 'miniapp_http=%s\n' "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "https://${DOMAIN}/mini-app/" 2>/dev/null || echo failed)"
REMOTE
}

remote_status_interactive() {
  local name
  name="$(select_remote 'Какой удалённый frontend проверить?')" || die "Удалённый frontend не выбран"
  remote_status_by_name "$name"
}
'''

    text = replace_once(
        text,
        '\nprint_menu() {\n',
        '\n' + remote_functions.strip('\n') + '\n\nprint_menu() {\n',
    )

    text = replace_once(
        text,
        '  8) Изменить сохранённый профиль\n  0) Выход',
        '  8) Изменить сохранённый профиль\n'
        '  9) Настроить удалённый frontend-сервер\n'
        ' 10) Обновить frontend на удалённом сервере\n'
        ' 11) Проверить удалённый frontend\n'
        '  0) Выход',
    )

    text = replace_once(
        text,
        '      8) edit_profile; pause ;;\n      0) exit 0 ;;',
        '      8) edit_profile; pause ;;\n'
        '      9) configure_remote_frontend; pause ;;\n'
        '      10) remote_update_interactive; pause ;;\n'
        '      11) remote_status_interactive; pause ;;\n'
        '      0) exit 0 ;;',
    )

    old_main = '''main() {
  require_root
  prepare_state
  install_bootstrap_tools
  main_menu
}

main "$@"
'''
    new_main = '''usage() {
  cat <<'USAGE'
Использование:
  sudo bash cdn.sh
  sudo bash cdn.sh --deploy-domain <domain>
  sudo bash cdn.sh --remote-deploy <remote-name>
  sudo bash cdn.sh --remote-status <remote-name>
USAGE
}

main() {
  require_root
  prepare_state
  install_bootstrap_tools

  case "${1:-}" in
    "") main_menu ;;
    --deploy-domain)
      [[ -n "${2:-}" ]] || die "Укажи домен после --deploy-domain"
      run_installer "$(normalize_domain "$2")" --deploy-only
      success "Frontend $(normalize_domain "$2") обновлён"
      ;;
    --remote-deploy)
      [[ -n "${2:-}" ]] || die "Укажи имя после --remote-deploy"
      remote_deploy_by_name "$2"
      ;;
    --remote-status)
      [[ -n "${2:-}" ]] || die "Укажи имя после --remote-status"
      remote_status_by_name "$2"
      ;;
    -h|--help) usage ;;
    *) usage; die "Неизвестный аргумент: $1" ;;
  esac
}

main "$@"
'''
    text = replace_once(text, old_main, new_main)

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

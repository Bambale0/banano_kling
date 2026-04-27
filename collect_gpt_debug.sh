#!/usr/bin/env bash
set +e
cd "$(dirname "$0")"

OUT="gpt_short.txt"
: > "$OUT"

section() {
  echo "" >> "$OUT"
  echo "============================================================" >> "$OUT"
  echo "$1" >> "$OUT"
  echo "============================================================" >> "$OUT"
}

run() {
  section "$1"
  shift
  echo "$ $*" >> "$OUT"
  "$@" >> "$OUT" 2>&1
  echo "EXIT_CODE=$?" >> "$OUT"
}

section "SYSTEM"
date >> "$OUT" 2>&1
pwd >> "$OUT" 2>&1
python3 --version >> "$OUT" 2>&1
node --version >> "$OUT" 2>&1
npm --version >> "$OUT" 2>&1

run "GIT STATUS" git status --short
run "GIT BRANCH" git branch --show-current
run "GIT LOG" git log --oneline -30

run "PY COMPILE CORE" python3 -m py_compile bot/keyboards.py bot/handlers/common.py bot/handlers/payments.py bot/miniapp.py bot/database.py bot/handlers/generation.py

section "IMPORTANT: OLD PRICE SEARCH IN BOT ONLY"
grep -R "150₽\|250₽\|400₽\|700₽\|1400₽\|15🍌\|30🍌\|50🍌\|100🍌\|200🍌\|15.*150\|30.*250\|50.*400\|100.*700\|200.*1400" -n bot --exclude-dir=__pycache__ >> "$OUT" 2>&1

section "IMPORTANT: NEW PRICE SEARCH IN BOT ONLY"
grep -R "65₽\|90₽\|160₽\|310₽\|605₽\|1500₽\|2900₽\|15.*65\|25.*90\|50.*160\|100.*310\|200.*605\|500.*1500\|1000.*2900" -n bot --exclude-dir=__pycache__ >> "$OUT" 2>&1

section "IMPORTANT: BALANCE/PAYMENT SOURCES"
grep -R "Пополнение баланса\|CryptoBot\|Мини\|Стандарт\|Оптимальный\|Про\|Студия\|Бизнес\|Максимум\|price_rub\|amount_rub\|amountRub\|PAYMENT_PACKAGES\|BANANA_PACKAGES\|get_balance\|menu_balance\|topup\|invoice" -n bot --exclude-dir=__pycache__ >> "$OUT" 2>&1

section "KEYBOARDS FULL PAYMENT CONTEXT"
grep -n "Пополнение\|CryptoBot\|Мини\|Стандарт\|Оптимальный\|Про\|Студия\|Бизнес\|Максимум\|150\|250\|400\|700\|1400\|65\|90\|160\|310\|605\|buy_\|pay_\|topup\|balance" bot/keyboards.py >> "$OUT" 2>&1
sed -n '730,830p' bot/keyboards.py >> "$OUT" 2>&1

section "PAYMENTS HANDLER CONTEXT"
grep -n "Пополнение\|CryptoBot\|Мини\|Стандарт\|Оптимальный\|Про\|Студия\|Бизнес\|Максимум\|150\|250\|400\|700\|1400\|65\|90\|160\|310\|605\|invoice\|amount\|credits\|callback_data\|topup" bot/handlers/payments.py >> "$OUT" 2>&1
sed -n '1,220p' bot/handlers/payments.py >> "$OUT" 2>&1

section "COMMON BALANCE CONTEXT"
grep -n "menu_balance\|balance\|CryptoBot\|Пополнение\|buy_\|pay_\|invoice\|topup" bot/handlers/common.py >> "$OUT" 2>&1
sed -n '430,520p' bot/handlers/common.py >> "$OUT" 2>&1

section "MINIAPP BACKEND PAYMENT CONTEXT"
grep -n "paymentPackages\|price_rub\|amount_rub\|amountRub\|Пополнение\|CryptoBot\|150\|250\|400\|700\|1400\|65\|90\|160\|310\|605\|topup\|invoice" bot/miniapp.py >> "$OUT" 2>&1
sed -n '700,790p' bot/miniapp.py >> "$OUT" 2>&1

section "MINI APP SOURCE OLD PRICES"
grep -R "price_rub:150\|price_rub:250\|price_rub:400\|price_rub:700\|price_rub:1400\|150₽\|250₽\|400₽\|700₽\|1400₽\|15.*150\|30.*250\|50.*400\|100.*700\|200.*1400" -n frontend/miniapp-v0 --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=out >> "$OUT" 2>&1

section "MINI APP SOURCE NEW PRICES"
grep -R "65₽\|90₽\|160₽\|310₽\|605₽\|1500₽\|2900₽\|15.*65\|25.*90\|50.*160\|100.*310\|200.*605\|500.*1500\|1000.*2900" -n frontend/miniapp-v0 --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=out >> "$OUT" 2>&1

section "MINI APP BUILT OUT OLD PRICES LIMITED"
grep -R "price_rub:150\|price_rub:250\|price_rub:400\|price_rub:700\|price_rub:1400\|150₽\|250₽\|400₽\|700₽\|1400₽" -n frontend/miniapp-v0/out 2>/dev/null | head -50 >> "$OUT" 2>&1

section "MINI APP FILES LIST"
find frontend/miniapp-v0 -maxdepth 3 -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.json' \) | sort >> "$OUT" 2>&1

section "SUPPORT SEARCH"
grep -R "@only_tany\|@chillcreative\|@S_k7222\|@s_k7222\|support\|Поддержка" -n bot frontend/miniapp-v0 --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=out >> "$OUT" 2>&1

section "QUALITY SEARCH"
grep -R "2K\|4K\|2k\|4k\|quality\|img_quality" -n bot frontend/miniapp-v0 --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=out >> "$OUT" 2>&1

section "RECENT LOGS LIMITED"
for f in logs/bot_output.log logs/bot.log bot_output.log bot.log; do
  if [ -f "$f" ]; then
    echo "--- tail $f ---" >> "$OUT"
    tail -80 "$f" >> "$OUT" 2>&1
  fi
done

section "DONE"
wc -c "$OUT" >> "$OUT" 2>&1
echo "Created $OUT" >> "$OUT"
echo "✅ Собрал диагностику в $OUT"

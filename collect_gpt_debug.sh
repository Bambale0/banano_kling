#!/usr/bin/env bash
set +e
cd "$(dirname "$0")"

OUT="gpt.txt"
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
run "GIT LOG" git log --oneline -20

run "PY COMPILE CORE" python3 -m py_compile bot/keyboards.py bot/handlers/common.py bot/miniapp.py bot/database.py bot/handlers/generation.py

run "SEARCH OLD PRICES" grep -R "150₽\|250₽\|400₽\|700₽\|1400₽\|15🍌\|30🍌\|50🍌\|100🍌\|200🍌" -n bot frontend/miniapp-v0
run "SEARCH NEW PRICES" grep -R "65₽\|90₽\|160₽\|310₽\|605₽\|1500₽\|2900₽" -n bot frontend/miniapp-v0
run "SEARCH BALANCE TEXT" grep -R "Пополнение баланса\|CryptoBot\|Мини:\|Стандарт:\|Оптимальный:\|Про:\|Студия:" -n bot frontend/miniapp-v0
run "SEARCH SUPPORT" grep -R "@only_tany\|@chillcreative\|@S_k7222\|@s_k7222\|support" -n bot frontend/miniapp-v0
run "SEARCH QUALITY" grep -R "2K\|4K\|2k\|4k\|quality\|img_quality" -n bot frontend/miniapp-v0

section "KEYBOARDS TOP"
sed -n '1,120p' bot/keyboards.py >> "$OUT" 2>&1

section "KEYBOARDS BALANCE FUNCTIONS"
grep -n "balance\|payment\|CryptoBot\|Мини\|Стандарт\|Оптимальный\|Студия\|buy_\|pay_" bot/keyboards.py >> "$OUT" 2>&1

section "COMMON BALANCE HANDLERS"
grep -n "menu_balance\|balance\|CryptoBot\|buy_\|pay_\|invoice\|payment" bot/handlers/common.py >> "$OUT" 2>&1
sed -n '430,520p' bot/handlers/common.py >> "$OUT" 2>&1

section "PAYMENT FILES"
for f in bot/handlers/payment.py bot/handlers/payments.py bot/services/cryptobot_service.py bot/services/payment_service.py bot/main.py bot/miniapp.py; do
  if [ -f "$f" ]; then
    echo "--- $f ---" >> "$OUT"
    grep -n "150\|250\|400\|700\|1400\|65\|90\|160\|310\|605\|CryptoBot\|invoice\|amount\|credits\|banana" "$f" >> "$OUT" 2>&1
  fi
done

section "MINI APP PRICE FILES"
for f in frontend/miniapp-v0/lib/api.ts frontend/miniapp-v0/lib/mock-data.ts frontend/miniapp-v0/components/balance-sheet.tsx frontend/miniapp-v0/components/payment-sheet.tsx frontend/miniapp-v0/components/workspace-sheet.tsx; do
  if [ -f "$f" ]; then
    echo "--- $f ---" >> "$OUT"
    grep -n "150\|250\|400\|700\|1400\|65\|90\|160\|310\|605\|banana\|credits\|amount\|price" "$f" >> "$OUT" 2>&1
  fi
done

section "RECENT LOGS"
for f in logs/bot_output.log logs/bot.log bot_output.log bot.log; do
  if [ -f "$f" ]; then
    echo "--- tail $f ---" >> "$OUT"
    tail -120 "$f" >> "$OUT" 2>&1
  fi
done

section "DONE"
echo "Created $OUT" >> "$OUT"
echo "✅ Собрал диагностику в $OUT"

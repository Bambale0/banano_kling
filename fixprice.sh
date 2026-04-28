#!/usr/bin/env bash
set -euo pipefail

echo "Applying tanyapi updates..."

python3 <<'PY'
import json
from pathlib import Path

price_path = Path("data/price.json")

data = json.loads(price_path.read_text(encoding="utf-8"))

prices = {
    "mini": 150,
    "start": 250,
    "optimal": 500,
    "pro": 1000,
    "studio": 1950,
    "business": 4900,
}

data["packages"] = [
    {**pkg, "price_rub": prices[pkg["id"]]}
    for pkg in data.get("packages", [])
    if pkg.get("id") in prices
]

# Уточняем стоимости моделей по ТЗ
data.setdefault("costs_reference", {}).setdefault("image_models", {}).update({
    "nano-banana-pro": 2.5,
    "banana_2": 2.5,
    "flux_pro": 2,
    "seedream_45": 1.5,
    "wan_27": 2.2,
})

data.setdefault("batch_pricing", {}).setdefault("base_costs", {}).update({
    "nano-banana-pro": 2.5,
    "banana_2": 2.5,
    "flux_pro": 2,
    "seedream_edit": 1.5,
    "wan_27": 2.2,
})

price_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

python3 <<'PY'
from pathlib import Path

path = Path("bot/keyboards.py")
text = path.read_text(encoding="utf-8")

text = text.replace(
    '    builder.button(text="📚 Промпт-канал", url="https://t.me/only_tm_ii")\n',
    "",
)

text = text.replace(
'''    if config.mini_app_url:
        builder.adjust(1, 2, 2, 2, 2, 1, 1)
    else:
        builder.adjust(2, 2, 2, 2, 1)
''',
'''    if config.mini_app_url:
        builder.adjust(1, 2, 2, 2, 2, 1)
    else:
        builder.adjust(2, 2, 2, 2, 1)
''',
)

text = text.replace(
'''    if config.mini_app_url:
        builder.adjust(1, 2, 2, 2, 2, 1, 1)
    else:
        builder.adjust(2, 2, 2, 2, 1, 1)
''',
'''    if config.mini_app_url:
        builder.adjust(1, 2, 2, 2, 2, 1)
    else:
        builder.adjust(2, 2, 2, 2, 1)
''',
)

path.write_text(text, encoding="utf-8")
PY

python3 <<'PY'
from pathlib import Path

path = Path("bot/handlers/common.py")
text = path.read_text(encoding="utf-8")

text = text.replace("    min_withdraw = 2000\n", "    min_withdraw = 1000\n")

old = '''        "<b>1 уровень</b> — ваш личный процент: <code>30%</code> от всех покупок ваших рефералов.\\n"
        "<b>2 уровень</b> — <code>7%</code> от покупок рефералов ваших рефералов.\\n\\n"
        "<b>Как это работает:</b>\\n"
        "• Пользователь переходит по вашей ссылке\\n"
        "• Регистрируется и закрепляется за вами навсегда\\n"
        "• После оплат рефералов начисляется денежное вознаграждение\\n\\n"
        "<b>2 уровень:</b>\\n"
        "Ваш реферал привёл ещё рефералов. За все их покупки вам также начисляется денежное вознаграждение — <code>7%</code>.\\n\\n"
        "• Вывод доступен после достижения минимальной суммы <code>1000₽</code>\\n"
        "• Каждый, кто перейдёт по вашей реферальной ссылке, получает 🍌 <code>25</code> бананов для тестирования бота\\n"
        "• За каждого приглашённого вами реферала вам начисляется + 🍌 <code>5</code> бананов\\n\\n"
'''

new = '''        "<b>1 уровень</b> — ваш личный процент: <code>30%</code> от всех покупок ваших рефералов.\\n"
        "<b>2 уровень</b> — <code>7%</code> от покупок рефералов ваших рефералов.\\n\\n"
        "<b>Как это работает:</b>\\n"
        "• Пользователь переходит по вашей ссылке\\n"
        "• Регистрируется и закрепляется за вами навсегда\\n"
        "• После оплат рефералов начисляется денежное вознаграждение\\n\\n"
        "<b>2 уровень:</b>\\n"
        "Ваш реферал привёл ещё рефералов. За все их покупки вам также начисляется денежное вознаграждение — <code>7%</code>.\\n\\n"
        "• Вывод доступен после достижения минимальной суммы <code>1000₽</code>\\n"
        "• Каждый, кто перейдёт по вашей реферальной ссылке, получает 🍌 <code>25</code> бананов для тестирования бота\\n"
        "• За каждого приглашённого вами реферала вам начисляется + 🍌 <code>5</code> бананов\\n\\n"
'''

text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
PY

echo "Validating JSON..."
python3 -m json.tool data/price.json >/dev/null

echo "Done."
echo
echo "Changed files:"
git diff -- data/price.json bot/keyboards.py bot/handlers/common.py

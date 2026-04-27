#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
from pathlib import Path
import json

p = Path("data/price.json")
data = json.loads(p.read_text(encoding="utf-8"))

data["credit_value"] = "Чем больше 🍌 — тем дешевле генерация"
data["support_contact"] = "@only_tany"

data["packages"] = [
    {"id": "mini", "name": "🍌 Мини", "credits": 15, "price_rub": 65, "bonus_credits": 0, "description": "Для пробы"},
    {"id": "start", "name": "🍌 Старт", "credits": 25, "price_rub": 90, "bonus_credits": 0, "description": "Удобный старт"},
    {"id": "optimal", "name": "🍌🍌 Оптимальный", "credits": 50, "price_rub": 160, "bonus_credits": 0, "popular": True, "description": "Лучшее соотношение цена/количество"},
    {"id": "pro", "name": "🍌🍌🍌 Про", "credits": 100, "price_rub": 310, "bonus_credits": 0, "description": "Для активных пользователей"},
    {"id": "studio", "name": "🍌🍌🍌🍌 Студия", "credits": 200, "price_rub": 605, "bonus_credits": 0, "description": "Для частой генерации"},
    {"id": "business", "name": "🍌🍌🍌🍌🍌 Бизнес", "credits": 500, "price_rub": 1500, "bonus_credits": 0, "description": "Выгодно для регулярной работы"},
    {"id": "max", "name": "🍌🍌🍌🍌🍌🍌 Максимум", "credits": 1000, "price_rub": 2900, "bonus_credits": 0, "description": "Самая выгодная цена за банан"},
]

costs = data.setdefault("costs_reference", {})
image = costs.setdefault("image_models", {})
image.update({
    "gemini_2_5_flash": 5,
    "gemini_3_pro": 5,
    "banana_2": 5,
    "z_image_turbo": 5,
    "seedream": 4,
    "seedream_45": 4,
    "flux_pro": 5,
    "nano-banana-pro": 5,
    "seedream_edit": 4,
    "grok_imagine_i2i": 3,
    "wan_27": 5,
})
legacy = costs.setdefault("legacy_keys", {})
legacy.update({
    "gemini_2_5_flash": 5,
    "gemini_3_pro": 5,
    "nanobanana": 5,
    "banana_pro": 5,
    "banana_2": 5,
    "seedream": 4,
    "seedream_edit": 4,
    "grok_imagine_i2i": 3,
    "wan_27": 5,
})

batch = data.setdefault("batch_pricing", {})
batch.setdefault("base_costs", {}).update({
    "gemini_2_5_flash": 5,
    "gemini_3_pro": 5,
    "banana_2": 5,
    "nano-banana-pro": 5,
    "seedream": 4,
    "seedream_edit": 4,
    "grok_imagine_i2i": 3,
    "wan_27": 5,
})
batch["upscale_costs"] = {"2K": 5, "4K": 7}

p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

python3 - <<'PY'
import json
from pathlib import Path
p = Path('data/price.json')
data = json.loads(p.read_text(encoding='utf-8'))
assert data['packages'][0]['price_rub'] == 65
assert data['packages'][1]['credits'] == 25
assert data['packages'][-1]['price_rub'] == 2900
assert data['batch_pricing']['upscale_costs']['4K'] == 7
assert data['support_contact'] == '@only_tany'
print('data/price.json updated correctly')
PY

echo "Restart bot after this: ./restart.sh"

#!/usr/bin/env bash
set -u

OUT="gpt.txt"
: > "$OUT"

log() {
  echo "$*" | tee -a "$OUT"
}

section() {
  echo "" | tee -a "$OUT"
  echo "==============================" | tee -a "$OUT"
  echo "$*" | tee -a "$OUT"
  echo "==============================" | tee -a "$OUT"
}

run() {
  echo "" | tee -a "$OUT"
  echo "> $*" | tee -a "$OUT"
  bash -lc "$*" >> "$OUT" 2>&1
  local code=$?
  echo "[exit: $code]" >> "$OUT"
  return $code
}

section "GPT MINI APP CHECK REPORT"
log "Date: $(date -Is)"
log "Repo: $(pwd)"
log "Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
log "Commit: $(git rev-parse HEAD 2>/dev/null || echo unknown)"

section "Git status"
run "git status --short"

section "Important files present"
for f in data/price.json bot/services/preset_manager.py bot/keyboards.py bot/handlers/common.py; do
  if [ -f "$f" ]; then
    log "OK: $f"
  else
    log "MISSING: $f"
  fi
done

section "Frontend / mini app files"
run "find frontend static -maxdepth 4 -type f 2>/dev/null | sort"

section "Search: series photo / batch / prepare series"
run "grep -RInE 'Серия фото|серия фото|Подготовить серию|batch|series|remove background|удалить фон|един.*стиль|preview|карточ' frontend static bot data 2>/dev/null | head -300"

section "Search: Nano Banana 2 in mini app/frontend"
run "grep -RInE 'Nano Banana 2|banana_2|model_banana_2|nanobanana|nano-banana' frontend static bot data 2>/dev/null | head -300"

section "Search: model price rendering / banana symbol"
run "grep -RInE 'price|cost|banana|банан|🍌|model.*cost|selectedModel|models' frontend static 2>/dev/null | head -300"

section "Search: buttons / horizontal overflow / layout classes"
run "grep -RInE 'button|btn|overflow|scroll|grid|flex|wrap|white-space|nowrap|rounded|pill|chip' frontend static 2>/dev/null | head -300"

section "Validate price.json and expected values"
python3 <<'PY' >> "$OUT" 2>&1
import json
from pathlib import Path
p = Path('data/price.json')
if not p.exists():
    print('ERROR: data/price.json missing')
    raise SystemExit(1)
data = json.loads(p.read_text(encoding='utf-8'))
expected_packages = {
    'mini': (15, 150),
    'start': (25, 250),
    'optimal': (50, 500),
    'pro': (100, 1000),
    'studio': (200, 1950),
    'business': (500, 4900),
}
print('Packages:')
for pkg in data.get('packages', []):
    print(f"- {pkg.get('id')}: credits={pkg.get('credits')} price={pkg.get('price_rub')}")
ids = {pkg.get('id') for pkg in data.get('packages', [])}
for pid, (credits, price) in expected_packages.items():
    pkg = next((x for x in data.get('packages', []) if x.get('id') == pid), None)
    if not pkg:
        print(f'FAIL package missing: {pid}')
    elif pkg.get('credits') != credits or pkg.get('price_rub') != price:
        print(f"FAIL package {pid}: expected {credits}/{price}, got {pkg.get('credits')}/{pkg.get('price_rub')}")
    else:
        print(f'OK package {pid}')
if 'max' in ids:
    print('FAIL package max still exists')
else:
    print('OK package max removed')

expected_models = {
    'nano-banana-pro': 2.5,
    'banana_2': 2.5,
    'flux_pro': 2,
    'seedream_45': 1.5,
    'seedream_edit': 1.5,
    'wan_27': 2.2,
}
print('\nImage model costs:')
image = data.get('costs_reference', {}).get('image_models', {})
for k, v in expected_models.items():
    actual = image.get(k)
    print(f'- {k}: {actual}')
    if actual != v:
        print(f'FAIL image_models.{k}: expected {v}, got {actual}')
legacy = data.get('costs_reference', {}).get('legacy_keys', {})
print('\nLegacy costs:')
for k in ['nanobanana', 'banana_pro', 'banana_2', 'seedream_edit', 'wan_27']:
    print(f'- {k}: {legacy.get(k)}')
batch = data.get('batch_pricing', {}).get('base_costs', {})
print('\nBatch costs:')
for k in ['nano-banana-pro', 'banana_2', 'flux_pro', 'seedream_edit', 'wan_27']:
    print(f'- {k}: {batch.get(k)}')
PY

section "Check preset_manager fractional-cost bug"
python3 <<'PY' >> "$OUT" 2>&1
from pathlib import Path
p = Path('bot/services/preset_manager.py')
text = p.read_text(encoding='utf-8') if p.exists() else ''
if 'return int(image_models[key])' in text or 'return int(legacy_keys[key])' in text:
    print('FAIL: preset_manager casts image prices to int; fractional prices will display/spend incorrectly')
else:
    print('OK: no direct int() cast found for image model costs')
if '_format_cost' in text:
    print('OK: _format_cost helper found')
else:
    print('WARN: _format_cost helper not found; verify fractional prices manually')
PY

section "Try import preset_manager and print model costs"
python3 <<'PY' >> "$OUT" 2>&1
try:
    from bot.services.preset_manager import preset_manager
    for model in ['nano-banana-pro','banana_2','seedream_edit','seedream_45','flux_pro','wan_27','banana_pro','nanobanana']:
        try:
            print(model, '=>', preset_manager.get_generation_cost(model))
        except Exception as e:
            print(model, 'ERROR', repr(e))
except Exception as e:
    print('IMPORT ERROR:', repr(e))
PY

section "Mini app diagnostics: likely broken points"
python3 <<'PY' >> "$OUT" 2>&1
from pathlib import Path
files = []
for root in ['frontend','static']:
    r = Path(root)
    if r.exists():
        files += [p for p in r.rglob('*') if p.is_file() and p.suffix.lower() in {'.js','.jsx','.ts','.tsx','.vue','.html','.css','.json'}]

checks = {
    'Nano Banana 2 visible in mini app': ['Nano Banana 2','banana_2','model_banana_2'],
    'Series photo feature': ['Серия фото','series','batch','Подготовить серию'],
    'Prepare series button handler': ['Подготовить серию','prepare','batch'],
    'Button wrapping CSS': ['flex-wrap','white-space','overflow-x','nowrap'],
}
for title, terms in checks.items():
    print('\n' + title)
    found = []
    for p in files:
        try:
            txt = p.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for term in terms:
            if term in txt:
                found.append((str(p), term))
                break
    if found:
        for p, term in found[:30]:
            print(f'FOUND {term}: {p}')
    else:
        print('NOT FOUND')
PY

section "Python syntax check for touched backend files"
run "python3 -m py_compile bot/services/preset_manager.py bot/keyboards.py bot/handlers/common.py"

section "Node/frontend checks if package.json exists"
if [ -f package.json ]; then
  run "cat package.json"
  if command -v npm >/dev/null 2>&1; then
    run "npm --version"
    run "npm run 2>&1 | sed -n '1,120p'"
  else
    log "npm not installed"
  fi
else
  log "No root package.json"
fi

section "SUMMARY"
cat <<'TXT' >> "$OUT"
Manual items to verify/fix from screenshots:
1. Mini app button chips overflow/overlap: inspect CSS for service chips and set flex-wrap: wrap; gap; max-width; no fixed narrow container; avoid white-space: nowrap for long Russian labels.
2. Series photo: verify the 'Подготовить серию' button has a click handler and sends correct route/callback/payload. Search section above should show implementation gaps.
3. Nano Banana 2: verify mini app model list includes banana_2 / Nano Banana 2, not only Nano Banana Pro.
4. Fractional prices: backend must not cast image costs through int(); otherwise 2.5 -> 2 and 1.5 -> 1.
5. Seedream 4.5: image_models.seedream_edit should be 1.5 if UI uses seedream_edit.
TXT

log ""
log "Report saved to $OUT"

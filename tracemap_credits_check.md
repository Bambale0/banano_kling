# Tracemap: Credit Types Audit (float vs int mismatch)

## Summary

The codebase has a fundamental **type mismatch** between the database schema and the application layer regarding credits. The DB schema defines `credits` as `INTEGER`, but the application increasingly treats credits as `float`/`REAL`. There are also several explicit `int()` casts that may cause silent truncation.

---

## File 1: `bot/database.py`

### Schema: `users.credits` = INTEGER (line 661)

```sql
credits INTEGER DEFAULT 0
```

### Schema: `transactions.credits` = INTEGER (line 760)

```sql
credits INTEGER NOT NULL
```

### Schema: `feed_remix_events.credits_spent` = REAL (line 503)

```sql
credits_spent REAL DEFAULT 0
```

### Schema: `prompt_repeat_events.credits_spent` = REAL (line 517)

```sql
credits_spent REAL DEFAULT 0
```

### Dataclass: `User.credits: float` (line 104)

**MISMATCH** ⚠️ DB stores it as `INTEGER`, Python type says `float`.

Created via `Credits(row["credits"] or 0)` throughout (lines 1156, 1287, 2497, 2583, 2597).

`Credits` is a `float` subclass (line 97) that displays ints cleanly but still stores floats.

### Dataclass: `Transaction.credits: int` (line 132)

This is correct for the DB schema (INTEGER).
However, `Transaction.promo_bonus_credits: int = 0` (line 138) is also correct for DB INTEGER.

### Dataclass: `GenerationTask.cost: Optional[int]` (line 564)

Correct — matches `cost INTEGER` in DB (line 852).

### Function: `get_promo_bonus_for_credits` (lines 237–240)

```python
def get_promo_bonus_for_credits(credits: float | int | str) -> int:
    amount = int(round(float(credits)))
    return int(PROMO_BONUS_BY_CREDITS.get(amount, 0))
```

OK — accepts float/int/str and rounds properly.

### Function: `complete_payment_atomic` (line 1857)

At line 1942:
```python
"UPDATE users SET credits = credits + ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
(transaction.credits, telegram_id),
```
OK — `transaction.credits` is `int`, DB column is `INTEGER`.

### Function: `credit_referral_commission` (line 2089)

```python
async def credit_referral_commission(
    telegram_id: int,
    transaction_credits: int,           # int
    transaction_amount_rub: Optional[float] = None,
    ...
)
```
At line 2121:
```python
base_value = float(
    transaction_amount_rub
    if transaction_amount_rub is not None
    else transaction_credits
)
```
**MISMATCH** ⚠️ `transaction_credits` is `int`, but when used as `base_value` it's `float` via `float()`, then used in SQL as `partner_total_revenue_rub = partner_total_revenue_rub + ?` (REAL column). This works but mixes credit values (INTEGER) with ruble amounts (REAL) in the same logic path.

### Function: `credit_first_payment_referral_bonus` (line 2190)

```python
async def credit_first_payment_referral_bonus(
    telegram_id: int,
    transaction_credits: int,
    ...
)
```
Same pattern — wraps `credit_referral_commission`. No additional mismatch.

### Function: `exchange_partner_balance_to_credits` (line 3214)

```python
async def exchange_partner_balance_to_credits(
    telegram_id: int, requested_amount_rub: float, rub_per_credit: float
)
```
Line 3254:
```python
credits_to_add = int(requested_amount_rub / rub_per_credit)
```
Then at line 3277:
```python
"UPDATE users SET credits = credits + ?, ..."
```
**SILENT TRUNCATION** ⚠️ `int()` truncates toward zero. If `requested_amount_rub / rub_per_credit = 2.99`, this gives 2 instead of 3. The check on line 3261 `if credits_to_add < 1` handles the lower bound, but fractional credits are silently lost.

### Function: `create_transaction` (line 4525)

```python
async def create_transaction(
    order_id: str,
    user_id: int,
    payment_id: str,
    provider: str,
    credits: int,                      # int
    amount_rub: float,
    ...
    promo_bonus_credits: int = 0,      # int
)
```
Line 4550:
```python
int(promo_bonus_credits or 0),
```
OK — matches DB `INTEGER`.

### Function: `get_user_credits` (line 4446)

```python
async def get_user_credits(telegram_id: int) -> int:
    user = await get_or_create_user(telegram_id)
    return int(user.credits)
```
**SILENT TRUNCATION** ⚠️ `int(user.credits)` — silently truncates fractional credits. If user has 2.5 credits, returns 2.

### Function: `add_credits` (line 4452)

```python
async def add_credits(telegram_id: int, amount: int) -> bool:
```
OK — `amount` is `int`, DB is `INTEGER`.

### Function: `deduct_credits` (line 4464)

```python
async def deduct_credits(
    telegram_id: int, amount: int, check_balance: bool = True
) -> bool:
```
OK — `amount` is `int`, DB is `INTEGER`.

### Function: `_credit_prompt_repeat_reward_in_db` (line 5163)

```python
async def _credit_prompt_repeat_reward_in_db(
    ...,
    credits_spent: Optional[float] = None,     # float
    amount_rub: float = PROMPT_REPEAT_REWARD_RUB,
)
```
Line 5184:
```python
float(credits_spent or 0),
```
OK — this inserts into DB column `credits_spent REAL`.

### Function: `credit_feed_prompt_repeat` (line 5212)

```python
async def credit_feed_prompt_repeat(
    source_generation_id: int | str,
    repeater_user_id: int,
    *,
    repeat_task_id: Optional[str] = None,
    credits_spent: Optional[float] = None,     # float
)
```
OK — passes to `_credit_prompt_repeat_reward_in_db`, both expect `float`.

### Function: `use_prompt` (line 5250)

```python
async def use_prompt(
    prompt_id: int,
    user_id: int,
    credits_spent: Optional[float] = None,     # float
)
```
OK — passes `credits_spent` as `float` to `_credit_prompt_repeat_reward_in_db`.

### Feed remix logic (lines 6264–6281)

Line 6264:
```python
credits_spent = float(row["cost"] or 0)   # cost is INTEGER in DB → converted to float
if credits_spent <= 0:
    ...
royalty = round(credits_spent * 0.05, 3)
```
Then at line 6272:
```python
source_author_id, remix_author_id, credits_spent, royalty_credits
```
Inserts into `feed_remix_events` where `credits_spent REAL` and `royalty_credits REAL` — OK, but `cost` from `generation_tasks` is `INTEGER`, converting it to `float` is safe but reveals the mixed type approach.

---

## File 2: `bot/payment_utils.py`

### Function: `package_bonus_credits` (line 9)

```python
def package_bonus_credits(package: dict[str, Any]) -> int:
    return int(package.get("bonus_credits", 0) or 0)
```
OK — returns `int`.

### Function: `total_package_credits` (line 13)

```python
def total_package_credits(package: dict[str, Any], promo_bonus: int = 0) -> int:
    return int(package["credits"]) + package_bonus_credits(package) + int(promo_bonus or 0)
```
OK — returns `int`.

### Function: `package_stars_amount` (line 17)

```python
def package_stars_amount(package: dict[str, Any]) -> int:
    explicit = package.get("price_stars", package.get("stars_price"))
    if explicit not in (None, ""):
        return max(1, int(round(float(explicit))))

    multiplier = max(0.01, float(config.TELEGRAM_STARS_PER_RUB or 1))
    flat_fee = max(0, int(config.TELEGRAM_STARS_FLAT_FEE or 0))
    return max(1, int(math.ceil(float(package["price_rub"]) * multiplier)) + flat_fee)
```
OK — returns `int` (stars amounts are integer).

### Function: `build_stars_invoice_payload` (line 28)

```python
def build_stars_invoice_payload(order_id: str, stars_amount: int) -> str:
    return f"{TELEGRAM_STARS_PAYLOAD_PREFIX}:{order_id}:{int(stars_amount)}"
```
OK — `int(int)` no-op but type-safe.

### Function: `parse_stars_invoice_payload` (line 32)

```python
def parse_stars_invoice_payload(payload: str | None) -> tuple[str, int] | None:
    ...
    stars_amount = int(parts[2])
    ...
```
OK — returns `int`.

**Conclusion for payment_utils.py**: No type mismatches. All credits and stars values are `int`.

---

## File 3: `bot/quality_pricing.py`

```python
QUALITY_COSTS = {"2k": 2.5, "2K": 2.5, "4k": 3.5, "4K": 3.5}
DEFAULT_QUALITY = "2K"
QUALITY_LABELS = {"2K": "2K качество — 2.5 🍌", "4K": "4K качество — 3.5 🍌"}
```

**KEY INSIGHT** ⚠️ Quality costs are **float** values (2.5, 3.5), but `users.credits` in the DB is `INTEGER`. 

These floats are used in `miniapp.py` as `credits_spent` and passed to `deduct_credits(telegram_id, amount=int)` or stored in DB columns like `credits_spent REAL`.

**Usage sites** (from grep):
- `bot/miniapp.py` line 2946: `QUALITY_COSTS.get(img_quality, ...)` → `unit_cost`
- `bot/miniapp.py` line 2988: `credits_spent=unit_cost` (float passed where `credits_spent: Optional[float]` is expected — OK in `_credit_prompt_repeat_reward_in_db`)
- `bot/miniapp.py` line 3131: same pattern
- `bot/miniapp.py` line 3184: same pattern
- `bot/miniapp.py` line 3597: `credits_spent=cost` 

**MISMATCH** ⚠️ The `deduct_credits` function (line 4464) accepts `amount: int`, but QUALITY_COSTS values are floats (2.5, 3.5). If these float values reach `deduct_credits` without a cast, Python will fail (TypeError: int expected for SQL 'credits - ?'). If they do get cast via `int()`, fractional credits are silently lost (2.5 → 2, 3.5 → 3).

---

## File 4: `bot/config.py`

No credits or cost definitions in `config.py`. Quality costs are in `quality_pricing.py`, not config.

---

## File 5: `bot/pricing_final.py`

```python
BANANA_RUB_BASE = 3
IMAGE_MODEL_COSTS = {
    "nanobanana": 5,
    "banana_pro": 5,
    ...
}
BANANA_PACKAGES = [
    {"credits": 15, "amount_rub": 65},
    {"credits": 25, "amount_rub": 90},
    ...
]
```

All values are **int**. No floats used. 
OK — no mismatches in this file.

---

## File 6: `tests/test_payment_utils.py`

All test functions use `int` values for credits and stars amounts:
- `package = {"credits": 25, "price_rub": 250, "price_stars": 199}` — int
- `package = {"credits": 15, "price_rub": 101}` — int
- `package = {"credits": 15, "price_rub": 150}` — int
- `package = {"credits": 25, "bonus_credits": 5, "price_rub": 250}` — int

**OK** — no mismatches in tests. But note: tests don't exercise the float credit path (QUALITY_COSTS).

---

## Type Mismatch Summary

| # | Location | Issue | Severity |
|---|----------|-------|----------|
| 1 | `database.py:104` — `User.credits: float` vs DB `INTEGER` (line 661) | Dataclass field `float` but DB column is `INTEGER`. Consistent with `Credits(float)` subclass but semantically incorrect if fractional credits exist. | ⚠️ Medium |
| 2 | `database.py:4446-4449` — `get_user_credits` does `int(user.credits)` | Silent truncation. If user has 2.5 credits, returns 2. | ⚠️ Medium |
| 3 | `database.py:3254` — `credits_to_add = int(requested_amount_rub / rub_per_credit)` in `exchange_partner_balance_to_credits` | Silent truncation on division. 2.99 → 2. | ⚠️ Medium |
| 4 | `database.py:2121` — `credit_referral_commission` mixes `transaction_credits` (int) with ruble amounts via `float()` | Cross-typing: credit values used where ruble floats are expected. Not a crash but a logical mixing. | ℹ️ Low |
| 5 | `quality_pricing.py:1` — `QUALITY_COSTS` are floats (2.5, 3.5) vs DB `credits INTEGER` | The quality/credits pricing system uses fractional values but the user balance column only stores integers. If these values reach `deduct_credits(amount: int)` without explicit `int()` cast, a TypeError would occur. | ⚠️ High |
| 6 | `database.py:503,504,517` — `credits_spent REAL` and `royalty_credits REAL` vs `users.credits INTEGER` | Mix of REAL and INTEGER for credit-related columns across different tables. `feed_remix_events.credits_spent` = REAL but `users.credits` = INTEGER. | ⚠️ Medium |

## Critical Findings

### 1. Fractional QUALITY_COSTS vs INTEGER credits balance
The quality system (2.5🍌, 3.5🍌) implies that a single generation can cost a fractional number of credits. But `users.credits` in the DB is `INTEGER DEFAULT 0`, meaning fractional credits can never exist in the user's balance. If 2.5 credits is deducted from a user with 3 credits, the result would be 0 (integer subtraction), not 0.5. This creates a gap between the pricing model and the balance storage.

### 2. `get_user_credits` truncates via `int()`
`get_user_credits` (line 4446-4449) does `return int(user.credits)`. If credits ever become fractional (e.g., via the QUALITY_COSTS path), this would return a misleading value.

### 3. `deduct_credits` expects `int` parameter
If a float from QUALITY_COSTS (like 2.5) is passed to `deduct_credits(amount: int)`, Python would generate a TypeError at runtime when Python tries to format the SQL: `"UPDATE users SET credits = credits - ?"` with a float where INTEGER is expected.

## Recommendation

**Option A**: Change `users.credits` to `REAL` across the board (schema, User dataclass, all functions). This makes fractional credits possible and aligns with QUALITY_COSTS. Update `deduct_credits`, `add_credits`, and `get_user_credits` to handle floats.

**Option B**: Change `QUALITY_COSTS` to integer values (3, 4 instead of 2.5, 3.5) and keep everything as int. This is simpler but increases base cost.

**Option C**: Keep QUALITY_COSTS as floats, but round them to nearest int before deduction (e.g., `round(2.5) = 2`, `round(3.5) = 4` with banker's rounding, or `math.ceil(2.5) = 3`). This hides the mismatch without fixing the fundamental inconsistency.

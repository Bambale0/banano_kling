from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYMENTS = ROOT / "bot" / "handlers" / "payments.py"
TEST_FILE = ROOT / "tests" / "standalone" / "test_lava_payment_reference.py"

source = PAYMENTS.read_text(encoding="utf-8")

old_extract = '''    if provider == "lava":
        invoice_id = lava_service.extract_invoice_id(result)
        payment_url = lava_service.extract_payment_url(result)
'''
new_extract = '''    contract_id = None
    if provider == "lava":
        invoice_id = lava_service.extract_invoice_id(result)
        contract_id = lava_service.extract_contract_id(result)
        payment_url = lava_service.extract_payment_url(result)
'''

if source.count(old_extract) != 1:
    raise RuntimeError(
        f"Expected one Lava invoice extraction block, found {source.count(old_extract)}"
    )
source = source.replace(old_extract, new_extract, 1)

old_payment_id = '''        payment_id=invoice_id,
        provider=provider,
'''
new_payment_id = '''        payment_id=contract_id or str(invoice_id),
        provider=provider,
'''

if source.count(old_payment_id) != 1:
    raise RuntimeError(
        f"Expected one transaction payment_id assignment, found {source.count(old_payment_id)}"
    )
source = source.replace(old_payment_id, new_payment_id, 1)
PAYMENTS.write_text(source, encoding="utf-8")

TEST_FILE.write_text(
    '''from pathlib import Path


def test_legacy_lava_initiate_payment_persists_contract_id():
    source = Path("bot/handlers/payments.py").read_text(encoding="utf-8")

    assert "contract_id = lava_service.extract_contract_id(result)" in source
    assert "payment_id=contract_id or str(invoice_id)" in source


def test_lava_checkout_and_legacy_flow_use_same_payment_reference_fallback():
    payments_source = Path("bot/handlers/payments.py").read_text(encoding="utf-8")
    checkout_source = Path("bot/handlers/lava_checkout.py").read_text(encoding="utf-8")

    expected = "contract_id or str(invoice_id)"
    assert expected in payments_source
    assert expected in checkout_source
''',
    encoding="utf-8",
)

print("Applied tanyapi Lava contractId payment reference fix")

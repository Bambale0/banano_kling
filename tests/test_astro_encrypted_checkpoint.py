"""Real persistent long-text checkpoints must not expose report prose in DB."""
import asyncio

from cryptography.fernet import Fernet

from bot.services.astro_encrypted_checkpoint import EncryptedCheckpointStore
from bot.services.astro_report_store import AstroReportSqlStore


def test_checkpoint_encryption_and_restart(tmp_path):
    async def run():
        db_path = str(tmp_path / "secret-report.db")
        key = Fernet.generate_key()
        first = EncryptedCheckpointStore(AstroReportSqlStore(db_path=db_path), key=key)
        args = {"owner_id": 100, "fingerprint": "a" * 64, "section_id": "section_01"}
        secret = "текст рождения и отношений для личного отчёта"
        assert await first.save_if_absent(**args, text=secret) == secret
        assert await first.read(**args) == secret
        assert secret.encode("utf-8") not in (tmp_path / "secret-report.db").read_bytes()
        new_instance = EncryptedCheckpointStore(AstroReportSqlStore(db_path=db_path), key=key)
        assert await new_instance.read(**args) == secret
        assert await new_instance.save_if_absent(**args, text="другая версия") == secret
    asyncio.run(run())

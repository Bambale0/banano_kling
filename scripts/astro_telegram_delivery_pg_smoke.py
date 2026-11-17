"""Destructive ONLY to a disposable localhost PostgreSQL astro_delivery_qa database."""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlsplit

import psycopg
from cryptography.fernet import Fernet
from pypdf import PdfReader

from bot import db
from bot.postgres_aiosqlite import PostgresConnection
from bot.services.astro_report_delivery import AstroTelegramDelivery
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_pipeline import load_report_plan


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_document(self, *, chat_id, document, caption):
        assert document.filename == "astro_neuromix.pdf"
        assert document.data.startswith(b"%PDF-")
        pdf = PdfReader(BytesIO(document.data), strict=True)
        assert "Синтетический текст тестового отчёта." in pdf.pages[0].extract_text()
        self.sent.append(("document", chat_id, len(document.data)))
        return SimpleNamespace(message_id=1234)

    async def send_message(self, *, chat_id, text):
        self.sent.append(("text", chat_id, len(text)))
        return SimpleNamespace(message_id=1235)


async def main():
    parsed = urlsplit(os.environ.get("DATABASE_URL", ""))
    assert parsed.scheme == "postgresql" and parsed.hostname == "127.0.0.1"
    assert parsed.port == 55443 and parsed.path == "/astro_delivery_qa"
    assert os.getenv("ASTRO_DELIVERY_PG_TEST_ACK") == "disposable-only"
    assert db.is_postgres()
    @asynccontextmanager
    async def isolated_pg_connection(_unused=None):
        # Use a disposable PostgreSQL without the application's unrelated legacy tables.
        raw = await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            yield PostgresConnection(raw)
        finally:
            await raw.close()
    db.connect = isolated_pg_connection
    jobs = AstroReportJobs(fingerprint_secret="synthetic-test-postgres-delivery",
                           data_key=Fernet.generate_key())
    now = int(time.time())
    report_id = await jobs.enqueue(
        owner_id=987654321, plan=load_report_plan("natal"),
        facts={"schema_version": "astro.natal-facts.v1", "chart": {
            "bodies": {"Sun": {"lon": 12.5}}}}, consent=True, now=now,
    )
    assert await jobs.claim(worker_id="qa-generator", now=now+1)
    assert await jobs.complete(job_id=report_id, worker_id="qa-generator", now=now+2,
                              report={"status": "completed", "service_id": "natal",
                                      "sections": [{"id": "intro", "title": "Обзор",
                                                    "text": "Синтетический текст тестового отчёта."}],
                                      "word_count": 4})
    bot = FakeBot()
    a = AstroTelegramDelivery(jobs=jobs, telegram_bot=bot, is_admin=lambda _: True)
    b = AstroTelegramDelivery(jobs=jobs, telegram_bot=bot, is_admin=lambda _: True)
    results = await asyncio.gather(a.run_once(now=now+3), b.run_once(now=now+3))
    assert sum(results) == 1, results
    assert len(bot.sent) == 1 and bot.sent[0][0] == "document"
    status = await jobs.status(owner_id=987654321,job_id=report_id,now=now+4)
    assert status["telegram_delivery"] == "delivered"
    assert await jobs.status(owner_id=987654322,job_id=report_id,now=now+4) is None
    assert not await a.run_once(now=now+5)
    await jobs.delete_owner(owner_id=987654321)
    assert await jobs.status(owner_id=987654321,job_id=report_id,now=now+6) is None
    print("POSTGRES_ASTRO_DELIVERY_OK native_ddl=yes concurrent_claim=1/2 delivered_once=yes owner_scoped=yes erase=yes")


if __name__ == "__main__":
    asyncio.run(main())

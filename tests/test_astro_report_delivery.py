"""User-visible Telegram delivery from durable, owner-scoped Astro outbox."""
import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader

from bot.services.astro_report_delivery import AstroTelegramDelivery
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_pdf import render_astro_pdf
from bot.services.astro_report_pipeline import load_report_plan


class TelegramFixture:
    def __init__(self, fail_once=False):
        self.documents = []
        self.messages = []
        self.fail_once = fail_once

    async def send_document(self, *, chat_id, document, caption):
        self.documents.append((chat_id, document, caption))
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError('synthetic Telegram transport timeout')
        return SimpleNamespace(message_id=4501)

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))
        return SimpleNamespace(message_id=4502)


def test_complete_report_delivered_to_own_telegram_and_never_twice(tmp_path):
    async def run():
        jobs = AstroReportJobs(db_path=str(tmp_path/'astro.db'),
                               fingerprint_secret='synthetic-astro-secret',
                               data_key=Fernet.generate_key())
        report_id = await jobs.enqueue(owner_id=99, plan=load_report_plan('natal'),
                                       facts={'schema_version':'astro.natal-facts.v1','chart':{'bodies':{'Sun':{'lon':1.0}}}},
                                       consent=True, now=100)
        claim = await jobs.claim(worker_id='astro-gen', now=101)
        assert claim and claim.job_id == report_id
        assert await jobs.complete(job_id=report_id, worker_id='astro-gen',now=102,
                                  report={'status':'completed','schema_version':'astro.report.v1',
                                          'service_id':'natal','word_count':10,
                                          'sections':[{'id':'intro','title':'Введение','text':'Пример полного отчёта.'}],
                                          'disclaimer':'Символическая интерпретация.'})
        bot = TelegramFixture()
        delivery = AstroTelegramDelivery(jobs=jobs, telegram_bot=bot, is_admin=lambda owner: owner==99)
        assert await delivery.run_once(now=103)
        assert bot.documents and bot.documents[0][0] == 99
        document = bot.documents[0][1]
        assert document.filename == 'astro_neuromix.pdf'
        assert document.data.startswith(b'%PDF-')
        reader = PdfReader(BytesIO(document.data))
        assert 'Пример полного отчёта.' in reader.pages[0].extract_text()
        assert 'Натальная карта' in bot.documents[0][2]
        state = await jobs.status(owner_id=99,job_id=report_id,now=104)
        assert state['telegram_delivery'] == 'delivered'
        assert state['report']['sections'][0]['text'] == 'Пример полного отчёта.'
        assert await jobs.status(owner_id=100, job_id=report_id, now=104) is None
        assert not await delivery.run_once(now=105)
        assert len(bot.documents) == 1
    asyncio.run(run())


def test_transient_telegram_failure_retries_from_persisted_outbox(tmp_path):
    async def run():
        jobs = AstroReportJobs(db_path=str(tmp_path/'retry.db'),
                               fingerprint_secret='synthetic-astro-secret',
                               data_key=Fernet.generate_key())
        report_id = await jobs.enqueue(owner_id=99, plan=load_report_plan('natal'),
                                       facts={'schema_version':'astro.natal-facts.v1','chart':{'bodies':{'Sun':{'lon':1.0}}}},
                                       consent=True, now=100)
        assert await jobs.claim(worker_id='gen',now=101)
        assert await jobs.complete(job_id=report_id,worker_id='gen',now=102,
                                  report={'status':'completed','service_id':'natal','sections':[{'id':'intro','title':'Введение','text':'Содержимое отчёта.'}],
                                          'word_count':2})
        first = AstroTelegramDelivery(jobs=jobs,telegram_bot=TelegramFixture(fail_once=True),is_admin=lambda _:True)
        assert await first.run_once(now=103)
        assert (await jobs.status(owner_id=99,job_id=report_id,now=104))['telegram_delivery']=='pending'
        second_bot=TelegramFixture()
        second=AstroTelegramDelivery(jobs=jobs,telegram_bot=second_bot,is_admin=lambda _:True)
        assert await second.run_once(now=200)
        assert len(second_bot.documents)==1
        retried = second_bot.documents[0][1]
        assert retried.filename == 'astro_neuromix.pdf'
        assert 'Содержимое отчёта.' in PdfReader(BytesIO(retried.data)).pages[0].extract_text()
        assert (await jobs.status(owner_id=99,job_id=report_id,now=201))['telegram_delivery']=='delivered'
    asyncio.run(run())


def test_terminal_failure_notifies_owner_without_report_payload(tmp_path):
    async def run():
        jobs = AstroReportJobs(db_path=str(tmp_path/'failed.db'),
                               fingerprint_secret='synthetic-astro-secret',
                               data_key=Fernet.generate_key())
        job_id = await jobs.enqueue(owner_id=99, plan=load_report_plan('natal'),
                                    facts={'schema_version':'astro.natal-facts.v1','chart':{}},
                                    consent=True, now=100)
        assert await jobs.claim(worker_id='gen',now=101)
        assert await jobs.reschedule(job_id=job_id,worker_id='gen',now=102,
                                     retry=False,error_code='temporary_provider_failure')
        bot=TelegramFixture()
        delivery=AstroTelegramDelivery(jobs=jobs,telegram_bot=bot,is_admin=lambda _:True)
        assert await delivery.run_once(now=103)
        assert len(bot.messages)==1 and bot.messages[0][0]==99
        assert 'Не удалось завершить' in bot.messages[0][1]
        assert 'Пример' not in bot.messages[0][1]
        assert not bot.documents
        assert (await jobs.status(owner_id=99,job_id=job_id,now=104))['telegram_delivery']=='delivered'
        assert not await delivery.run_once(now=105)
    asyncio.run(run())


def test_revoked_admin_never_receives_private_astrological_report(tmp_path):
    async def run():
        jobs = AstroReportJobs(db_path=str(tmp_path/'revoked.db'),
                               fingerprint_secret='synthetic-astro-secret',
                               data_key=Fernet.generate_key())
        job_id = await jobs.enqueue(owner_id=99,plan=load_report_plan('natal'),
                                    facts={'schema_version':'astro.natal-facts.v1','chart':{}},
                                    consent=True,now=100)
        assert await jobs.claim(worker_id='gen',now=101)
        assert await jobs.complete(job_id=job_id,worker_id='gen',now=102,
                                  report={'status':'completed','service_id':'natal',
                                          'sections':[{'id':'a','title':'Тест','text':'Приватный раздел.'}]})
        bot=TelegramFixture()
        delivery=AstroTelegramDelivery(jobs=jobs,telegram_bot=bot,is_admin=lambda _:False)
        assert await delivery.run_once(now=103)
        assert not bot.documents and not bot.messages
        assert (await jobs.status(owner_id=99,job_id=job_id,now=104))['telegram_delivery']=='failed'
    asyncio.run(run())


def test_erasing_owner_removes_undelivered_telegram_outbox(tmp_path):
    async def run():
        jobs=AstroReportJobs(db_path=str(tmp_path/'erase.db'),
                             fingerprint_secret='synthetic-astro-secret',
                             data_key=Fernet.generate_key())
        job_id=await jobs.enqueue(owner_id=99,plan=load_report_plan('natal'),
                                  facts={'schema_version':'astro.natal-facts.v1','chart':{}},
                                  consent=True,now=100)
        assert await jobs.claim(worker_id='gen',now=101)
        assert await jobs.reschedule(job_id=job_id,worker_id='gen',now=102,
                                     retry=False,error_code='temporary_provider_failure')
        assert await jobs.delete_owner(owner_id=99)==1
        bot=TelegramFixture()
        delivery=AstroTelegramDelivery(jobs=jobs,telegram_bot=bot,is_admin=lambda _:True)
        assert not await delivery.run_once(now=103)
        assert await jobs.status(owner_id=99,job_id=job_id,now=104) is None
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["revoke", "erase", "group", "invalid_pdf"])
def test_private_delivery_fails_closed_at_export_boundary(tmp_path, mode):
    async def run():
        jobs = AstroReportJobs(db_path=str(tmp_path/'private.db'),
                               fingerprint_secret='synthetic-secret', data_key=Fernet.generate_key())
        owner = -99 if mode == 'group' else 99
        if mode == 'group':
            with pytest.raises(ValueError, match='Invalid report owner'):
                await jobs.enqueue(owner_id=owner, plan=load_report_plan('natal'),
                                   facts={'schema_version':'astro.natal-facts.v1','chart':{}},
                                   consent=True, now=100)
            return
        job_id = await jobs.enqueue(owner_id=owner, plan=load_report_plan('natal'),
                                    facts={'schema_version':'astro.natal-facts.v1','chart':{}},
                                    consent=True, now=100)
        assert await jobs.claim(worker_id='gen', now=101)
        report = {'status':'completed','service_id':'natal',
                  'sections':[{'title':'Тест','text':'Приватный текст.'}]}
        assert await jobs.complete(job_id=job_id, worker_id='gen', report=report, now=102)
        authorized = True

        async def exporting(*args, **kwargs):
            nonlocal authorized
            if mode == 'revoke':
                authorized = False
            elif mode == 'erase':
                await jobs.delete_owner(owner_id=owner)
            elif mode == 'invalid_pdf':
                raise ValueError('synthetic invalid report')
            return render_astro_pdf(report)

        bot = TelegramFixture()
        delivery = AstroTelegramDelivery(jobs=jobs, telegram_bot=bot,
                                          is_admin=lambda _: authorized)
        with patch('bot.services.astro_report_delivery.asyncio.to_thread', exporting):
            assert await delivery.run_once(now=103)
        assert not bot.documents and not bot.messages
        if mode == 'erase':
            assert await jobs.status(owner_id=owner, job_id=job_id, now=104) is None
        else:
            state = await jobs.status(owner_id=owner, job_id=job_id, now=104)
            assert state['telegram_delivery'] in ('cancelled', 'failed')
            assert state['status'] == 'completed'  # Mini App keeps the original report.
    asyncio.run(run())

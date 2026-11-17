"""PG adapter ignores generic CREATE: Astro must use native DDL only."""
import asyncio

from cryptography.fernet import Fernet

from bot import db
from bot.services.astro_report_jobs import AstroReportJobs
from bot.services.astro_report_store import AstroReportSqlStore


class FakePgConnection:
    def __init__(self):
        self.native = []
        self.regular = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def execute_native_ddl(self, sql):
        assert sql.lstrip().upper().startswith('CREATE ')
        self.native.append(sql)

    async def execute(self, sql, _parameters=None):
        if sql.lstrip().upper().startswith('CREATE '):
            raise AssertionError('PG schema DDL was silently ignored by SQL translator')
        self.regular.append(sql)

    async def commit(self):
        return None


def test_astrological_tables_use_native_ddl_on_pg(monkeypatch):
    connection = FakePgConnection()
    monkeypatch.setattr(db, 'is_postgres', lambda: True)
    monkeypatch.setattr(db, 'connect', lambda *args, **kwargs: connection)

    async def check():
        await AstroReportJobs(
            fingerprint_secret='testing-astro-fingerprint',
            data_key=Fernet.generate_key(),
        ).initialize()
        await AstroReportSqlStore().initialize()

    asyncio.run(check())
    statements = '\n'.join(connection.native).lower()
    assert 'create table if not exists astro_report_jobs' in statements
    assert 'create table if not exists astro_report_sections' in statements
    assert 'create table if not exists astro_report_circuit' in statements
    assert statements.count('create index if not exists') >= 3
    assert any('insert into astro_report_circuit' in statement.lower()
               for statement in connection.regular)

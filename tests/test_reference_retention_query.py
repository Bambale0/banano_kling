"""Reference ownership SQL must survive the real PostgreSQL adapter."""

import pytest

from bot.postgres_aiosqlite import translate_sql
from bot.services.reference_retention import reference_snapshot_query


@pytest.mark.parametrize("all_uploads", [False, True])
def test_snapshot_query_does_not_invent_bound_parameters(all_uploads):
    query = reference_snapshot_query(postgres=True, all_uploads=all_uploads)
    translated = translate_sql(query)
    assert translated is not None
    # The collector calls execute(query) without bind parameters. A JSONPath
    # question mark used to become %s inside the quoted path and break parsing.
    assert "%s" not in translated

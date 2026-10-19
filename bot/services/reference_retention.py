"""Read every persisted input slot before deciding that a reference is orphaned.

The collector deliberately keeps references from pending, failed and private
works as well as public results. A malformed owner document raises a database
error: deletion must not continue with an incomplete ownership graph.
"""

REFERENCE_DOCUMENTS_SQL = """
    SELECT request_data AS document FROM generation_tasks
    WHERE request_data LIKE '%uploads/refs/%'
    UNION ALL
    SELECT feed_repeat_reference_selection AS document FROM generation_tasks
    WHERE feed_repeat_reference_selection LIKE '%uploads/refs/%'
    UNION ALL
    SELECT result_urls AS document FROM generation_tasks
    WHERE result_urls LIKE '%uploads/refs/%'
    UNION ALL
    SELECT generation_settings AS document FROM user_prompts
    WHERE generation_settings LIKE '%uploads/refs/%'
"""


def reference_snapshot_query(*, postgres: bool, all_uploads: bool = False) -> str:
    """Return a backend-specific read-only query over all nested media slots."""
    if postgres:
        # Keep predicates outside JSONPath: the compatibility adapter treats
        # question marks as bind placeholders, even inside quoted literals.
        leaves = """
            SELECT DISTINCT ref.value #>> '{}' AS ref_url
            FROM snapshots
            CROSS JOIN LATERAL jsonb_path_query(
                snapshots.document::jsonb,
                'strict $.**'
            ) AS ref(value)
            WHERE jsonb_typeof(ref.value) = 'string'
              AND (ref.value #>> '{}') LIKE '%uploads/refs/%'
        """
    else:
        leaves = """
            SELECT DISTINCT CAST(ref.value AS TEXT) AS ref_url
            FROM snapshots, json_tree(snapshots.document) AS ref
            WHERE ref.type = 'text'
              AND CAST(ref.value AS TEXT) LIKE '%uploads/refs/%'
        """
    documents = REFERENCE_DOCUMENTS_SQL
    if all_uploads:
        documents = documents.replace("%uploads/refs/%", "%uploads/%")
        leaves = leaves.replace("%uploads/refs/%", "%uploads/%")
    return f"WITH snapshots AS ({documents}) {leaves}"

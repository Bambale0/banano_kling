"""Portable additive schema, shared by SQLite and native PostgreSQL bootstrap."""

REFERENCE_LIBRARY_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS reference_categories (
        id TEXT PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, name_key)
    )""",
    """CREATE TABLE IF NOT EXISTS reference_category_items (
        category_id TEXT NOT NULL REFERENCES reference_categories(id) ON DELETE CASCADE,
        reference_id BIGINT NOT NULL REFERENCES saved_references(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(category_id, reference_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_reference_category_items_reference ON reference_category_items(reference_id)",
    "CREATE INDEX IF NOT EXISTS idx_reference_categories_user ON reference_categories(user_id)",
)

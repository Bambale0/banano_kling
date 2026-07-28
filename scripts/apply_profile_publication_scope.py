from pathlib import Path
import re


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise AssertionError(
            f"{path}: expected one exact anchor, got {count}: {old[:120]!r}"
        )
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise AssertionError(
            f"{path}: expected one regex anchor, got {count}: {pattern[:120]!r}"
        )
    write(path, next_text)


def patch_database() -> None:
    path = "bot/database.py"
    replace_once(
        path,
        '''        ("is_public_feed", "ALTER TABLE generation_tasks ADD COLUMN is_public_feed BOOLEAN DEFAULT 0"),
        ("is_prompt_library", "ALTER TABLE generation_tasks ADD COLUMN is_prompt_library BOOLEAN DEFAULT 0"),''',
        '''        ("is_public_feed", "ALTER TABLE generation_tasks ADD COLUMN is_public_feed BOOLEAN DEFAULT 0"),
        ("is_profile_visible", "ALTER TABLE generation_tasks ADD COLUMN is_profile_visible BOOLEAN DEFAULT 0"),
        ("is_adult_content", "ALTER TABLE generation_tasks ADD COLUMN is_adult_content BOOLEAN DEFAULT 0"),
        ("is_prompt_library", "ALTER TABLE generation_tasks ADD COLUMN is_prompt_library BOOLEAN DEFAULT 0"),''',
    )
    replace_once(
        path,
        '''    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_published ON generation_tasks(is_public_feed, status, feed_published_at DESC, created_at DESC)"
    )''',
        '''    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_safe ON generation_tasks(is_public_feed, is_adult_content, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_profile ON generation_tasks(user_id, is_profile_visible, status, created_at DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_published ON generation_tasks(is_public_feed, status, feed_published_at DESC, created_at DESC)"
    )''',
    )
    replace_once(
        path,
        '''def generation_feed_blurred(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "feed_blurred", False))


def generation_prompt_hidden(''',
        '''def generation_feed_blurred(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "feed_blurred", False))


def generation_profile_visible(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(
        _generation_attr(generation, "is_profile_visible", False)
        or _generation_attr(generation, "is_public_feed", False)
    )


def generation_adult_content(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> bool:
    return bool(_generation_attr(generation, "is_adult_content", False))


def generation_publication_scope(
    generation: GenerationTask | dict[str, Any] | db_backend.Row | None,
) -> str:
    if bool(_generation_attr(generation, "is_public_feed", False)) and not generation_adult_content(generation):
        return "feed"
    if generation_profile_visible(generation):
        return "profile"
    return "private"


def generation_prompt_hidden(''',
    )
    replace_once(
        path,
        '''                "result_url IS NOT NULL",
                "is_public_feed = 1",
            ]''',
        '''                "result_url IS NOT NULL",
                "is_public_feed = 1",
                "COALESCE(is_adult_content, 0) = 0",
            ]''',
    )
    replace_once(
        path,
        '''        "feed_references_visible": references_visible,
        "feed_blurred": generation_feed_blurred(row),
    }''',
        '''        "feed_references_visible": references_visible,
        "feed_blurred": generation_feed_blurred(row),
        "is_profile_visible": generation_profile_visible(row),
        "is_adult_content": generation_adult_content(row),
        "publication_scope": generation_publication_scope(row),
        "feed_interactions_enabled": generation_publication_scope(row) == "feed",
    }''',
    )
    replace_once(
        path,
        '''        "gt.result_url IS NOT NULL",
        "gt.is_public_feed = 1",
    ]''',
        '''        "gt.result_url IS NOT NULL",
        "gt.is_public_feed = 1",
        "COALESCE(gt.is_adult_content, 0) = 0",
    ]''',
    )
    replace_once(
        path,
        '''async def get_user_feed_generations(
    user_id: int,
    limit: int = 120,
    offset: int = 0,
    *,
    include_unpublished_owned: bool = False,
    include_unavailable: bool = False,
) -> list[dict[str, Any]]:
    """Return user feed items."""
    limit = max(0, int(limit or 0))
    offset = max(0, int(offset or 0))
    where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.is_public_feed = 1
    """
    if include_unpublished_owned:
        where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.source_feed_gen_id IS NULL
        """''',
        '''async def get_user_feed_generations(
    user_id: int,
    limit: int = 120,
    offset: int = 0,
    *,
    include_unpublished_owned: bool = False,
    profile_visible_only: bool = False,
    include_unavailable: bool = False,
) -> list[dict[str, Any]]:
    """Return publications for a user profile or the legacy public-only view."""
    limit = max(0, int(limit or 0))
    offset = max(0, int(offset or 0))
    where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.is_public_feed = 1
              AND COALESCE(gt.is_adult_content, 0) = 0
    """
    if profile_visible_only:
        where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND (COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)
        """
    elif include_unpublished_owned:
        where_clause = """
            WHERE gt.user_id = ?
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND gt.source_feed_gen_id IS NULL
        """''',
    )
    replace_once(
        path,
        '''async def get_user_feed_summary(user_id: int) -> dict[str, int]:
    cards = await get_user_feed_generations(user_id, limit=0, include_unavailable=True)''',
        '''async def get_user_feed_summary(user_id: int) -> dict[str, int]:
    cards = await get_user_feed_generations(
        user_id,
        limit=0,
        profile_visible_only=True,
        include_unavailable=True,
    )''',
    )
    replace_once(
        path,
        '''              AND gt.result_url IS NOT NULL
              AND gt.is_public_feed = 1
            LIMIT 1''',
        '''              AND gt.result_url IS NOT NULL
              AND gt.is_public_feed = 1
              AND COALESCE(gt.is_adult_content, 0) = 0
            LIMIT 1''',
    )
    replace_once(
        path,
        '''    return _generation_row_to_card(row, viewer_user_id=viewer_user_id, include_unavailable=include_unavailable)


async def get_public_feed_generation''',
        '''    return _generation_row_to_card(row, viewer_user_id=viewer_user_id, include_unavailable=include_unavailable)


async def get_profile_generation_card(
    gen_id: int | str,
    *,
    viewer_user_id: Optional[int] = None,
    include_unavailable: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        value = str(gen_id).strip()
        if value.isdigit():
            clause, param = "gt.id = ?", int(value)
        else:
            clause, param = "gt.task_id = ?", value
        cursor = await db.execute(
            f"""
            SELECT gt.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code,
                   u.photo_url AS author_photo_url,
                   (
                       SELECT COUNT(*)
                       FROM generation_tasks child
                       WHERE child.parent_generation_id = gt.id
                         AND child.status = 'completed'
                   ) AS remix_count,
                   (
                       SELECT COUNT(*)
                       FROM feed_comments fc
                       WHERE fc.generation_id = gt.id
                   ) AS comments_count
            FROM generation_tasks gt
            LEFT JOIN users u ON u.id = gt.user_id
            WHERE {clause}
              AND gt.type IN ('image', 'video')
              AND gt.status = 'completed'
              AND gt.result_url IS NOT NULL
              AND (COALESCE(gt.is_profile_visible, 0) = 1 OR gt.is_public_feed = 1)
            LIMIT 1
            """,
            (param,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return _generation_row_to_card(
        row,
        viewer_user_id=viewer_user_id,
        include_unavailable=include_unavailable,
    )


async def get_public_feed_generation''',
    )
    regex_once(
        path,
        r'''async def share_to_feed\(.*?\n\nasync def set_feed_blurred\(''',
        '''async def share_to_feed(
    gen_id: int | str,
    user_id: int,
    *,
    prompt_visible: bool = False,
    references_visible: bool = False,
    blurred: Optional[bool] = None,
    publication_scope: str = "feed",
    adult_content: bool = False,
) -> Optional[dict[str, Any]]:
    normalized_scope = str(publication_scope or "feed").strip().lower()
    if normalized_scope not in {"feed", "profile"}:
        normalized_scope = "feed"

    adult_content = bool(adult_content)
    if adult_content:
        normalized_scope = "profile"

    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, user_id=user_id)
        if (
            not row
            or row["type"] not in FEED_PUBLIC_TYPES
            or row["status"] != "completed"
            or not row["result_url"]
            or row["source_feed_gen_id"] is not None
            or not _feed_result_urls(row)
        ):
            return None

        result_urls = _generation_result_urls(row)
        if result_urls:
            from bot.services.feed_persist import persist_feed_result_urls

            persisted = await persist_feed_result_urls(result_urls)
            result_url = persisted[0] if persisted else row["result_url"]
            result_urls_json = json.dumps(persisted, ensure_ascii=False) if persisted else None
        else:
            result_url = row["result_url"]
            result_urls_json = None

        published_at = datetime.utcnow().isoformat(sep=" ", timespec="microseconds")
        next_blurred = generation_feed_blurred(row) if blurred is None else bool(blurred)
        if adult_content:
            next_blurred = True
        is_public_feed = normalized_scope == "feed" and not adult_content
        await db.execute(
            """
            UPDATE generation_tasks
            SET is_public_feed = ?,
                is_profile_visible = 1,
                is_adult_content = ?,
                feed_prompt_visible = ?,
                feed_references_visible = ?,
                feed_blurred = ?,
                feed_published_at = ?,
                result_url = ?,
                result_urls = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(is_public_feed),
                int(adult_content),
                int(bool(prompt_visible)),
                int(bool(references_visible)),
                int(next_blurred),
                published_at,
                result_url,
                result_urls_json,
                row["id"],
            ),
        )
        await db.commit()
        internal_id = row["id"]

    if is_public_feed:
        return await get_feed_generation_card(internal_id, viewer_user_id=user_id)
    return await get_profile_generation_card(internal_id, viewer_user_id=user_id)


async def set_feed_blurred(''',
    )
    regex_once(
        path,
        r'''async def set_feed_blurred\(.*?\n\nasync def remove_from_feed\(''',
        '''async def set_feed_blurred(
    gen_id: int | str,
    user_id: int,
    blurred: bool,
    *,
    allow_any_user: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH, timeout=15) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(
            db,
            gen_id,
            user_id=None if allow_any_user else user_id,
        )
        if not row or not generation_profile_visible(row):
            return None
        await db.execute(
            "UPDATE generation_tasks SET feed_blurred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(bool(blurred)), row["id"]),
        )
        await db.commit()
        internal_id = row["id"]

    if generation_publication_scope(row) == "feed":
        return await get_feed_generation_card(internal_id, viewer_user_id=user_id)
    return await get_profile_generation_card(internal_id, viewer_user_id=user_id)


async def remove_from_feed(''',
    )
    replace_once(
        path,
        '''        await db.execute(
            "UPDATE generation_tasks SET is_public_feed = 0, feed_published_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )''',
        '''        await db.execute(
            """
            UPDATE generation_tasks
            SET is_public_feed = 0,
                is_profile_visible = 0,
                is_adult_content = 0,
                feed_published_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )''',
    )
    # Direct comment lookup must also reject an impossible adult/public row.
    replace_once(
        path,
        '''              AND is_public_feed = 1
            LIMIT 1''',
        '''              AND is_public_feed = 1
              AND COALESCE(is_adult_content, 0) = 0
            LIMIT 1''',
    )


def patch_miniapp() -> None:
    path = "bot/miniapp.py"
    replace_once(
        path,
        '''    get_feed_generation_card,
    get_feed_generations,''',
        '''    get_feed_generation_card,
    get_feed_generations,
    get_profile_generation_card,''',
    )
    replace_once(
        path,
        '''    get_user_stats,
    increment_feed_share,''',
        '''    get_user_stats,
    generation_adult_content,
    generation_profile_visible,
    generation_publication_scope,
    increment_feed_share,''',
    )
    replace_once(
        path,
        '''               source_feed_gen_id, feed_prompt_visible, feed_references_visible,
               feed_blurred, created_at''',
        '''               source_feed_gen_id, feed_prompt_visible, feed_references_visible,
               feed_blurred, is_profile_visible, is_adult_content, created_at''',
    )
    text = read(path)
    old = '''                       source_feed_gen_id, feed_prompt_visible, feed_references_visible,
                       feed_blurred, created_at, request_data'''
    if text.count(old) != 3:
        raise AssertionError(
            f"{path}: expected 3 task-detail SELECT anchors, got {text.count(old)}"
        )
    text = text.replace(
        old,
        '''                       source_feed_gen_id, feed_prompt_visible, feed_references_visible,
                       feed_blurred, is_profile_visible, is_adult_content, created_at, request_data''',
    )
    write(path, text)
    replace_once(
        path,
        '''                "feed_blurred": bool(row["feed_blurred"]) if "feed_blurred" in row.keys() else False,
                "feed_id": row["id"],''',
        '''                "feed_blurred": bool(row["feed_blurred"]) if "feed_blurred" in row.keys() else False,
                "is_profile_visible": generation_profile_visible(row),
                "is_adult_content": generation_adult_content(row),
                "publication_scope": generation_publication_scope(row),
                "feed_interactions_enabled": generation_publication_scope(row) == "feed",
                "feed_id": row["id"],''',
    )
    replace_once(
        path,
        '''        "feed_blurred": bool(row["feed_blurred"]) if "feed_blurred" in row.keys() else False,
        "created_at": row["created_at"],''',
        '''        "feed_blurred": bool(row["feed_blurred"]) if "feed_blurred" in row.keys() else False,
        "is_profile_visible": generation_profile_visible(row),
        "is_adult_content": generation_adult_content(row),
        "publication_scope": generation_publication_scope(row),
        "feed_interactions_enabled": generation_publication_scope(row) == "feed",
        "created_at": row["created_at"],''',
    )
    text = read(path)
    text, count = re.subn(
        r'''(get_user_feed_generations\(\n\s+user\.id,\n\s+limit=limit,\n\s+offset=offset,\n)(\s+include_unavailable=True,)''',
        r'''\1            profile_visible_only=True,
\2''',
        text,
        count=2,
        flags=re.S,
    )
    if count != 2:
        raise AssertionError(f"{path}: expected two profile feed calls, got {count}")
    write(path, text)
    replace_once(
        path,
        '''        blurred = None
        if "blurred" in body or "feed_blurred" in body:
            blurred = _payload_bool(
                body.get("blurred", body.get("feed_blurred")),
                False,
            )
        telegram_id, ctx = await _get_user_context''',
        '''        blurred = None
        if "blurred" in body or "feed_blurred" in body:
            blurred = _payload_bool(
                body.get("blurred", body.get("feed_blurred")),
                False,
            )
        publication_scope = str(
            body.get("publication_scope", body.get("scope", "feed")) or "feed"
        ).strip().lower()
        adult_content = _payload_bool(
            body.get("adult_content", body.get("is_adult_content")),
            False,
        )
        telegram_id, ctx = await _get_user_context''',
    )
    replace_once(
        path,
        '''            references_visible=references_visible,
            blurred=blurred,
        )''',
        '''            references_visible=references_visible,
            blurred=blurred,
            publication_scope=publication_scope,
            adult_content=adult_content,
        )''',
    )
    replace_once(
        path,
        '''{"ok": False, "error": "Нельзя опубликовать эту генерацию в ленту"}''',
        '''{"ok": False, "error": "Нельзя опубликовать эту генерацию"}''',
    )


def patch_schema() -> None:
    path = "schema_postgres.sql"
    replace_once(
        path,
        '''    is_public_feed BOOLEAN DEFAULT FALSE,
    is_prompt_library BOOLEAN DEFAULT FALSE,''',
        '''    is_public_feed BOOLEAN DEFAULT FALSE,
    is_profile_visible BOOLEAN DEFAULT FALSE,
    is_adult_content BOOLEAN DEFAULT FALSE,
    is_prompt_library BOOLEAN DEFAULT FALSE,''',
    )
    replace_once(
        path,
        '''    feed_prompt_visible BOOLEAN DEFAULT FALSE,
    feed_references_visible BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,''',
        '''    feed_prompt_visible BOOLEAN DEFAULT FALSE,
    feed_references_visible BOOLEAN DEFAULT FALSE,
    feed_blurred BOOLEAN DEFAULT FALSE,
    feed_published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,''',
    )
    replace_once(
        path,
        '''CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_source_feed''',
        '''CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed ON generation_tasks(is_public_feed, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_feed_safe ON generation_tasks(is_public_feed, is_adult_content, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_profile ON generation_tasks(user_id, is_profile_visible, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_tasks_source_feed''',
    )


def patch_frontend_contracts() -> None:
    types_path = "frontend/miniapp-v0/lib/types.ts"
    text = read(types_path)
    old = '''  feed_blurred?: boolean
}'''
    if text.count(old) != 2:
        raise AssertionError(
            f"{types_path}: expected 2 feed_blurred interfaces, got {text.count(old)}"
        )
    write(
        types_path,
        text.replace(old, '''  feed_blurred?: boolean
  is_adult_content?: boolean
}'''),
    )

    api_path = "frontend/miniapp-v0/lib/api.ts"
    replace_once(
        api_path,
        '''    referencesVisible?: boolean
    blurred?: boolean
  } = {}''',
        '''    referencesVisible?: boolean
    blurred?: boolean
    publicationScope?: 'profile' | 'feed'
    adultContent?: boolean
  } = {}''',
    )
    replace_once(
        api_path,
        '''    references_visible: Boolean(options.referencesVisible),
    feed_blurred: Boolean(options.blurred),''',
        '''    references_visible: Boolean(options.referencesVisible),
    feed_blurred: Boolean(options.blurred),
    publication_scope: options.publicationScope || 'feed',
    adult_content: Boolean(options.adultContent),''',
    )


def patch_task_detail() -> None:
    path = "frontend/miniapp-v0/components/task-detail-panel.tsx"
    replace_once(
        path,
        '''  Banana, ExternalLink, Copy, RefreshCw, Headphones, UserRound, Images, BookOpen, Eye, EyeOff
} from 'lucide-react' ''',
        '''  Banana, ExternalLink, Copy, RefreshCw, Headphones, UserRound, Images, BookOpen, Eye, EyeOff, ShieldAlert
} from 'lucide-react' ''',
    )
    replace_once(
        path,
        '''  const [feedReferencesVisible, setFeedReferencesVisible] = useState(false)
  const [feedBlurred, setFeedBlurred] = useState(false)''',
        '''  const [feedReferencesVisible, setFeedReferencesVisible] = useState(false)
  const [feedBlurred, setFeedBlurred] = useState(false)
  const [publicationScope, setPublicationScope] = useState<'profile' | 'feed'>('feed')
  const [adultContent, setAdultContent] = useState(false)''',
    )
    replace_once(
        path,
        '''    setFeedReferencesVisible(Boolean(taskDetail?.feed_references_visible))
    setFeedBlurred(Boolean(taskDetail?.feed_blurred))
  }, [''',
        '''    setFeedReferencesVisible(Boolean(taskDetail?.feed_references_visible))
    setFeedBlurred(Boolean(taskDetail?.feed_blurred))
    setPublicationScope(taskDetail?.publication_scope === 'profile' ? 'profile' : 'feed')
    setAdultContent(Boolean(taskDetail?.is_adult_content))
  }, [''',
    )
    replace_once(
        path,
        '''    taskDetail?.feed_references_visible,
    taskDetail?.feed_blurred,
  ])''',
        '''    taskDetail?.feed_references_visible,
    taskDetail?.feed_blurred,
    taskDetail?.publication_scope,
    taskDetail?.is_adult_content,
  ])''',
    )
    replace_once(
        path,
        '''  const handlePublish = async () => {
    if (!taskDetail || publishBusy) return
    if (!taskDetail.is_public_feed && !confirmPublication('ленту работ')) return''',
        '''  const isPublished = Boolean(taskDetail?.is_profile_visible || taskDetail?.is_public_feed)

  const handlePublish = async () => {
    if (!taskDetail || publishBusy) return
    const target = publicationScope === 'profile' ? 'свой профиль' : 'ленту и свой профиль'
    if (!isPublished && !confirmPublication(target)) return''',
    )
    replace_once(
        path,
        '''      if (taskDetail.is_public_feed) {
        await unpublishGeneration(taskDetail.task_id)
        updateTask(taskDetail.task_id, { is_public_feed: false })
        notifyFeedChanged()
        toast.success('Убрано из ленты')
      } else {
        await publishGeneration(taskDetail.task_id, {
          promptVisible: feedPromptVisible,
          referencesVisible: feedReferencesVisible,
          blurred: feedBlurred,
        })
        updateTask(taskDetail.task_id, {
          is_public_feed: true,
          feed_prompt_visible: feedPromptVisible,
          feed_references_visible: feedReferencesVisible,
          feed_blurred: feedBlurred,
        })
        notifyFeedChanged()
        toast.success('Опубликовано в ленте')
      }''',
        '''      if (isPublished) {
        await unpublishGeneration(taskDetail.task_id)
        updateTask(taskDetail.task_id, {
          is_public_feed: false,
          is_profile_visible: false,
          publication_scope: 'private',
          is_adult_content: false,
        })
        notifyFeedChanged()
        toast.success('Публикация убрана')
      } else {
        const published = await publishGeneration(taskDetail.task_id, {
          promptVisible: feedPromptVisible,
          referencesVisible: feedReferencesVisible,
          blurred: feedBlurred,
          publicationScope,
          adultContent,
        })
        updateTask(taskDetail.task_id, {
          is_public_feed: published.publication_scope === 'feed',
          is_profile_visible: true,
          publication_scope: published.publication_scope,
          is_adult_content: Boolean(published.is_adult_content),
          feed_interactions_enabled: published.feed_interactions_enabled,
          feed_prompt_visible: feedPromptVisible,
          feed_references_visible: feedReferencesVisible,
          feed_blurred: Boolean(published.feed_blurred),
        })
        notifyFeedChanged()
        toast.success(
          published.publication_scope === 'profile'
            ? 'Опубликовано только в профиле'
            : 'Опубликовано в ленте и профиле'
        )
      }''',
    )
    replace_once(
        path,
        '''  const handleUpdateFeedSettings = async () => {
    if (!taskDetail || publishBusy || !taskDetail.is_public_feed) return''',
        '''  const handleUpdateFeedSettings = async () => {
    if (!taskDetail || publishBusy || !isPublished) return''',
    )
    replace_once(
        path,
        '''      await publishGeneration(taskDetail.task_id, {
        promptVisible: feedPromptVisible,
        referencesVisible: feedReferencesVisible,
        blurred: feedBlurred,
      })
      updateTask(taskDetail.task_id, {
        is_public_feed: true,
        feed_prompt_visible: feedPromptVisible,
        feed_references_visible: feedReferencesVisible,
        feed_blurred: feedBlurred,
      })
      notifyFeedChanged()
      toast.success('Настройки ленты обновлены')''',
        '''      const published = await publishGeneration(taskDetail.task_id, {
        promptVisible: feedPromptVisible,
        referencesVisible: feedReferencesVisible,
        blurred: feedBlurred,
        publicationScope,
        adultContent,
      })
      updateTask(taskDetail.task_id, {
        is_public_feed: published.publication_scope === 'feed',
        is_profile_visible: true,
        publication_scope: published.publication_scope,
        is_adult_content: Boolean(published.is_adult_content),
        feed_interactions_enabled: published.feed_interactions_enabled,
        feed_prompt_visible: feedPromptVisible,
        feed_references_visible: feedReferencesVisible,
        feed_blurred: Boolean(published.feed_blurred),
      })
      notifyFeedChanged()
      toast.success('Настройки публикации обновлены')''',
    )
    replace_once(
        path,
        '''                <div className="rounded-xl border border-border/50 bg-secondary/35 p-3">
                  <div className="grid grid-cols-3 gap-2">''',
        '''                <div className="rounded-xl border border-border/50 bg-secondary/35 p-3">
                  <div className="mb-3 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      disabled={adultContent}
                      onClick={() => setPublicationScope('feed')}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',
                        publicationScope === 'feed'
                          ? 'border-cyan/40 bg-cyan/10 text-cyan'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      Лента и профиль
                    </button>
                    <button
                      type="button"
                      onClick={() => setPublicationScope('profile')}
                      className={cn(
                        'rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
                        publicationScope === 'profile'
                          ? 'border-cyan/40 bg-cyan/10 text-cyan'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      Только профиль
                    </button>
                  </div>
                  {taskDetail.type === 'image' ? (
                    <button
                      type="button"
                      onClick={() => {
                        setAdultContent((current) => {
                          const next = !current
                          if (next) {
                            setPublicationScope('profile')
                            setFeedBlurred(true)
                          }
                          return next
                        })
                      }}
                      className={cn(
                        'mb-3 flex w-full items-start gap-2 rounded-lg border p-3 text-left transition-colors',
                        adultContent
                          ? 'border-destructive/40 bg-destructive/10 text-destructive'
                          : 'border-border/50 bg-background/40 text-muted-foreground'
                      )}
                    >
                      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>
                        <span className="block text-xs font-semibold">Контент 18+</span>
                        <span className="mt-0.5 block text-[11px] leading-relaxed">
                          Публикуется только в профиле и всегда скрывается блюром. В общей ленте его не будет.
                        </span>
                      </span>
                    </button>
                  ) : null}
                  <div className="grid grid-cols-3 gap-2">''',
    )
    replace_once(path, '''              {taskDetail.is_public_feed ? (
                <Button''', '''              {isPublished ? (
                <Button''')
    replace_once(path, "                  Обновить ленту", "                  Обновить публикацию")
    replace_once(
        path,
        "                {taskDetail.is_public_feed ? 'Убрать из ленты' : 'В ленту'}",
        "                {isPublished ? 'Убрать публикацию' : 'Опубликовать'}",
    )


def patch_profile() -> None:
    path = "frontend/miniapp-v0/components/tabs/profile-tab.tsx"
    replace_once(
        path,
        '''  fetchProfileFeed,
  saveProfileChannel,
  shareFeedItem,''',
        '''  fetchProfileFeed,
  saveProfileChannel,
  setFeedItemBlurred,
  shareFeedItem,''',
    )
    replace_once(
        path,
        '''  ExternalLink,
  Grid3X3,
  Heart,''',
        '''  ExternalLink,
  Eye,
  EyeOff,
  Grid3X3,
  Heart,''',
    )
    replace_once(
        path,
        '''  const [feedRefreshToken, setFeedRefreshToken] = useState(0)''',
        '''  const [feedRefreshToken, setFeedRefreshToken] = useState(0)
  const [revealedIds, setRevealedIds] = useState<Set<number>>(() => new Set())''',
    )
    replace_once(
        path,
        '''  async function handleSaveChannel() {''',
        '''  async function handleToggleBlur(item: FeedItem) {
    if (!isLive || !(item.can_blur || item.is_mine)) return
    setBusyId(item.id)
    try {
      const updated = await setFeedItemBlurred(item.id, !item.feed_blurred)
      setItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      setRevealedIds((prev) => {
        const next = new Set(prev)
        next.delete(item.id)
        return next
      })
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось обновить blur'))
    } finally {
      setBusyId(null)
    }
  }

  function revealItem(item: FeedItem) {
    setRevealedIds((prev) => new Set(prev).add(item.id))
  }

  async function handleSaveChannel() {''',
    )
    # The same media class occurs once for video and once for image.
    text = read(path)
    old = '''                      className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
                    />'''
    if text.count(old) != 2:
        raise AssertionError(f"{path}: expected two grid media anchors, got {text.count(old)}")
    text = text.replace(
        old,
        '''                      className={cn(
                        'h-full w-full object-cover transition-all duration-500 group-hover:scale-[1.04]',
                        item.feed_blurred && !revealedIds.has(item.id) && 'scale-110 blur-xl'
                      )}
                    />''',
    )
    write(path, text)
    replace_once(
        path,
        '''                <span className="pointer-events-none absolute inset-0 bg-background/0 transition-colors group-hover:bg-background/35" />''',
        '''                <span className="pointer-events-none absolute inset-0 bg-background/0 transition-colors group-hover:bg-background/35" />
                {item.feed_blurred && !revealedIds.has(item.id) ? (
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      revealItem(item)
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        event.stopPropagation()
                        revealItem(item)
                      }
                    }}
                    className="absolute inset-0 z-10 flex cursor-pointer flex-col items-center justify-center gap-1 bg-background/25 text-center text-foreground backdrop-blur-[2px]"
                  >
                    <Eye className="h-5 w-5" />
                    <span className="rounded-full bg-background/80 px-2 py-1 text-[10px] font-semibold">
                      {item.is_adult_content ? 'Показать 18+' : 'Показать'}
                    </span>
                  </span>
                ) : null}''',
    )
    text = read(path)
    old = '''                className="max-h-full w-auto max-w-full object-contain"
              />'''
    if text.count(old) != 2:
        raise AssertionError(f"{path}: expected two preview media anchors, got {text.count(old)}")
    text = text.replace(
        old,
        '''                className={cn(
                  'max-h-full w-auto max-w-full object-contain transition-all',
                  previewItem.feed_blurred && !revealedIds.has(previewItem.id) && 'scale-105 blur-2xl'
                )}
              />''',
    )
    write(path, text)
    replace_once(
        path,
        '''          {previewReferences.length ? (''',
        '''          {previewItem.feed_blurred && !revealedIds.has(previewItem.id) ? (
            <button
              type="button"
              onClick={() => revealItem(previewItem)}
              className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-background/25 text-foreground"
            >
              <Eye className="h-7 w-7" />
              <span className="rounded-full bg-background/85 px-4 py-2 text-sm font-semibold backdrop-blur">
                {previewItem.is_adult_content ? 'Показать контент 18+' : 'Показать изображение'}
              </span>
            </button>
          ) : null}
          {previewReferences.length ? (''',
    )
    replace_once(
        path,
        '''            <Button
              type="button"
              className="h-10 rounded-full px-4"
              disabled={!feedInteractionsEnabled(previewItem)}
              onClick={() => handleRemix(previewItem)}
            >''',
        '''            {previewItem.can_blur || previewItem.is_mine ? (
              <Button
                type="button"
                variant="secondary"
                className="h-10 rounded-full px-4"
                disabled={!isLive || busyId === previewItem.id}
                onClick={() => handleToggleBlur(previewItem)}
              >
                {previewItem.feed_blurred ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                <span>{previewItem.feed_blurred ? 'Убрать blur' : 'Blur'}</span>
              </Button>
            ) : null}
            <Button
              type="button"
              className="h-10 rounded-full px-4"
              disabled={!feedInteractionsEnabled(previewItem)}
              onClick={() => handleRemix(previewItem)}
            >''',
    )


def patch_tests() -> None:
    path = "tests/test_database.py"
    text = read(path)
    marker = "\n\n@pytest.mark.asyncio\nasync def test_cleanup_stale_local_generation_tasks_refunds_old_img_tasks"
    if marker not in text:
        raise AssertionError(f"{path}: insertion marker missing")
    tests = r'''

@pytest.mark.asyncio
async def test_profile_only_publication_is_hidden_from_general_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile_scope.db"))
    await database.init_db()
    user = await database.get_or_create_user(440001)
    await database.add_generation_task(
        user.id, user.telegram_id, "profile-only-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="portrait", cost=2,
    )
    await database.complete_video_task(
        "profile-only-task", "https://example.com/profile-only.png"
    )

    card = await database.share_to_feed(
        "profile-only-task", user.id, publication_scope="profile", blurred=True
    )

    assert card is not None
    assert card["publication_scope"] == "profile"
    assert card["is_profile_visible"] is True
    assert card["feed_interactions_enabled"] is False
    assert card["feed_blurred"] is True
    assert await database.get_feed_generations(limit=20) == []
    profile_cards = await database.get_user_feed_generations(
        user.id, profile_visible_only=True, include_unavailable=True
    )
    assert [item["id"] for item in profile_cards] == [card["id"]]


@pytest.mark.asyncio
async def test_adult_content_is_forced_to_blurred_profile_only(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "adult_scope.db"))
    await database.init_db()
    user = await database.get_or_create_user(440002)
    await database.add_generation_task(
        user.id, user.telegram_id, "adult-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="adult portrait", cost=2,
    )
    await database.complete_video_task("adult-task", "https://example.com/adult.png")

    card = await database.share_to_feed(
        "adult-task",
        user.id,
        publication_scope="feed",
        adult_content=True,
        blurred=False,
    )

    assert card is not None
    assert card["publication_scope"] == "profile"
    assert card["is_adult_content"] is True
    assert card["feed_blurred"] is True
    assert card["feed_interactions_enabled"] is False
    assert await database.get_feed_generations(limit=20) == []


@pytest.mark.asyncio
async def test_feed_publication_is_visible_in_feed_and_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "feed_scope.db"))
    await database.init_db()
    user = await database.get_or_create_user(440003)
    await database.add_generation_task(
        user.id, user.telegram_id, "feed-and-profile-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="safe portrait", cost=2,
    )
    await database.complete_video_task(
        "feed-and-profile-task", "https://example.com/feed.png"
    )

    card = await database.share_to_feed(
        "feed-and-profile-task", user.id, publication_scope="feed"
    )

    assert card is not None
    assert card["publication_scope"] == "feed"
    assert card["is_profile_visible"] is True
    assert card["feed_interactions_enabled"] is True
    assert [item["id"] for item in await database.get_feed_generations(limit=20)] == [card["id"]]
    profile_cards = await database.get_user_feed_generations(
        user.id, profile_visible_only=True, include_unavailable=True
    )
    assert [item["id"] for item in profile_cards] == [card["id"]]


@pytest.mark.asyncio
async def test_profile_owner_can_toggle_blur_without_general_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile_blur.db"))
    await database.init_db()
    user = await database.get_or_create_user(440004)
    await database.add_generation_task(
        user.id, user.telegram_id, "profile-blur-task", "image", "banana_pro",
        model="banana_pro", aspect_ratio="1:1", prompt="portrait", cost=2,
    )
    await database.complete_video_task(
        "profile-blur-task", "https://example.com/profile-blur.png"
    )
    published = await database.share_to_feed(
        "profile-blur-task", user.id, publication_scope="profile"
    )
    updated = await database.set_feed_blurred(published["id"], user.id, True)

    assert updated is not None
    assert updated["publication_scope"] == "profile"
    assert updated["feed_blurred"] is True
    assert await database.get_feed_generations(limit=20) == []
'''
    write(path, text.replace(marker, tests + marker, 1))


def patch_docs() -> None:
    path = "tracemap_feed_referral.md"
    replace_once(
        path,
        '''`completed generation`
-> user chooses share/publish
-> generation row marked public/feed-visible
-> feed card becomes queryable
-> likes/shares/comments/remix routes reference same generation''',
        '''`completed generation`
-> user chooses `Лента и профиль` or `Только профиль`
-> `Лента и профиль`: safe publication is visible on both surfaces
-> `Только профиль`: publication never enters the general feed
-> content marked `18+` is forced to `Только профиль` and blur
-> likes/shares/comments/remix remain available only for general-feed publications''',
    )


def main() -> None:
    patch_database()
    patch_miniapp()
    patch_schema()
    patch_frontend_contracts()
    patch_task_detail()
    patch_profile()
    patch_tests()
    patch_docs()
    Path("scripts/apply_profile_publication_scope.py").unlink()


if __name__ == "__main__":
    main()

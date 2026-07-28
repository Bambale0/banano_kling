from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one anchor, got {count}: {old[:140]!r}")
    write(path, text.replace(old, new, 1))


def patch_database() -> None:
    path = "bot/database.py"
    replace_once(
        path,
        '        "feed_interactions_enabled": generation_publication_scope(row) == "feed",',
        '        "feed_interactions_enabled": generation_profile_visible(row),',
    )

    replace_once(
        path,
        '''async def add_feed_comment(
    gen_id: int | str,
    user_id: int,
    text: str,
) -> Optional[dict[str, Any]]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return None
    normalized = normalized[:500]
    try:
        internal_id = int(gen_id)
    except (TypeError, ValueError):
        return None

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        generation_cursor = await db.execute(
            """
            SELECT *
            FROM generation_tasks
            WHERE id = ?
              AND type IN ('image', 'video')
              AND status = 'completed'
              AND result_url IS NOT NULL
              AND is_public_feed = 1
            LIMIT 1
            """,
            (internal_id,),
        )
        generation = await generation_cursor.fetchone()
        if not generation or not _feed_result_urls(generation):
            return None

        cursor = await db.execute(
            """
            INSERT INTO feed_comments (generation_id, user_id, text)
            VALUES (?, ?, ?)
            """,
            (internal_id, user_id, normalized),
        )
        comment_id = cursor.lastrowid
        await db.commit()

        row_cursor = await db.execute(
            """
            SELECT fc.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code
            FROM feed_comments fc
            LEFT JOIN users u ON u.id = fc.user_id
            WHERE fc.id = ?
            """,
            (comment_id,),
        )
        row = await row_cursor.fetchone()
    return _feed_comment_row_to_payload(row, viewer_user_id=user_id) if row else None
''',
        '''async def add_feed_comment(
    gen_id: int | str,
    user_id: int,
    text: str,
    *,
    allow_profile: bool = False,
) -> Optional[dict[str, Any]]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return None
    normalized = normalized[:500]
    try:
        internal_id = int(gen_id)
    except (TypeError, ValueError):
        return None

    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        generation = await _fetch_generation_row(
            db,
            internal_id,
            public_only=not allow_profile,
        )
        if (
            not generation
            or (allow_profile and not generation_profile_visible(generation))
            or not _feed_result_urls(generation)
        ):
            return None

        cursor = await db.execute(
            """
            INSERT INTO feed_comments (generation_id, user_id, text)
            VALUES (?, ?, ?)
            """,
            (internal_id, user_id, normalized),
        )
        comment_id = cursor.lastrowid
        await db.commit()

        row_cursor = await db.execute(
            """
            SELECT fc.*, u.telegram_id AS author_telegram_id,
                   u.username AS author_username,
                   u.first_name AS author_first_name,
                   u.last_name AS author_last_name,
                   u.referral_code AS author_referral_code
            FROM feed_comments fc
            LEFT JOIN users u ON u.id = fc.user_id
            WHERE fc.id = ?
            """,
            (comment_id,),
        )
        row = await row_cursor.fetchone()
    return _feed_comment_row_to_payload(row, viewer_user_id=user_id) if row else None
''',
    )

    replace_once(
        path,
        '''async def like_feed_generation(gen_id: int | str, user_id: int) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, public_only=True)
        if not row or not _feed_result_urls(row):
            return None
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO feed_generation_likes (user_id, generation_task_id)
            VALUES (?, ?)
            """,
            (user_id, row["id"]),
        )
        if cursor.rowcount > 0:
            await db.execute(
                "UPDATE generation_tasks SET likes_count = likes_count + 1 WHERE id = ?",
                (row["id"],),
            )
        await db.commit()
        internal_id = row["id"]
    return await get_feed_generation_card(internal_id, viewer_user_id=user_id)


async def increment_feed_share(gen_id: int | str) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, public_only=True)
        if not row or not _feed_result_urls(row):
            return None
        await db.execute(
            "UPDATE generation_tasks SET shares_count = shares_count + 1 WHERE id = ?",
            (row["id"],),
        )
        await db.commit()
        internal_id = row["id"]
    return await get_feed_generation_card(internal_id)
''',
        '''async def like_feed_generation(
    gen_id: int | str,
    user_id: int,
    *,
    allow_profile: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, public_only=not allow_profile)
        if (
            not row
            or (allow_profile and not generation_profile_visible(row))
            or not _feed_result_urls(row)
        ):
            return None
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO feed_generation_likes (user_id, generation_task_id)
            VALUES (?, ?)
            """,
            (user_id, row["id"]),
        )
        if cursor.rowcount > 0:
            await db.execute(
                "UPDATE generation_tasks SET likes_count = likes_count + 1 WHERE id = ?",
                (row["id"],),
            )
        await db.commit()
        internal_id = row["id"]
        scope = generation_publication_scope(row)
    if scope == "feed":
        return await get_feed_generation_card(internal_id, viewer_user_id=user_id)
    return await get_profile_generation_card(internal_id, viewer_user_id=user_id)


async def increment_feed_share(
    gen_id: int | str,
    *,
    allow_profile: bool = False,
) -> Optional[dict[str, Any]]:
    async with db_backend.connect(DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await _fetch_generation_row(db, gen_id, public_only=not allow_profile)
        if (
            not row
            or (allow_profile and not generation_profile_visible(row))
            or not _feed_result_urls(row)
        ):
            return None
        await db.execute(
            "UPDATE generation_tasks SET shares_count = shares_count + 1 WHERE id = ?",
            (row["id"],),
        )
        await db.commit()
        internal_id = row["id"]
        scope = generation_publication_scope(row)
    if scope == "feed":
        return await get_feed_generation_card(internal_id)
    return await get_profile_generation_card(internal_id)
''',
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
        '''        card = await get_feed_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )''',
        '''        card = await get_profile_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )''',
    )

    replace_once(
        path,
        '''async def miniapp_feed_like(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await like_feed_generation(gen_id, ctx["user"].id)
        if not card:
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed like failed")
''',
        '''async def miniapp_feed_like(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await like_feed_generation(
            gen_id,
            ctx["user"].id,
            allow_profile=allow_profile,
        )
        if not card:
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)
        return web.json_response({"ok": True, "feed_item": card})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed like failed")
''',
    )

    replace_once(
        path,
        '''        gen_id = body.get("gen_id") or body.get("task_id")
        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await increment_feed_share(gen_id)
        if not card:
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)''',
        '''        gen_id = body.get("gen_id") or body.get("task_id")
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        telegram_id, _ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        card = await increment_feed_share(gen_id, allow_profile=allow_profile)
        if not card:
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)''',
    )

    replace_once(
        path,
        '''async def miniapp_feed_comments(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        limit = min(max(int(body.get("limit", 80) or 80), 1), 150)
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        comments = await get_feed_comments(
            gen_id,
            limit=limit,
            viewer_user_id=ctx["user"].id,
        )
        return web.json_response({"ok": True, "comments": comments})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed comments failed")
''',
        '''async def miniapp_feed_comments(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        limit = min(max(int(body.get("limit", 80) or 80), 1), 150)
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        getter = get_profile_generation_card if allow_profile else get_feed_generation_card
        card = await getter(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        if not card:
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)
        comments = await get_feed_comments(
            gen_id,
            limit=limit,
            viewer_user_id=ctx["user"].id,
        )
        return web.json_response({"ok": True, "comments": comments})
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed comments failed")
''',
    )

    replace_once(
        path,
        '''async def miniapp_feed_comment_add(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        text = str(body.get("text", "") or "")
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        comment = await add_feed_comment(gen_id, ctx["user"].id, text)
        if not comment:
            return web.json_response(
                {"ok": False, "error": "Комментарий не удалось добавить"},
                status=400,
            )
        card = await get_feed_generation_card(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        return web.json_response(
            {
                "ok": True,
                "comment": comment,
                "comments_count": int((card or {}).get("comments_count") or 0),
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed comment add failed")
''',
        '''async def miniapp_feed_comment_add(request: web.Request) -> web.Response:
    try:
        body = await _miniapp_payload(request)
        init_data = body.get("init_data", "")
        gen_id = body.get("gen_id") or body.get("task_id")
        text = str(body.get("text", "") or "")
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"
        _telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        comment = await add_feed_comment(
            gen_id,
            ctx["user"].id,
            text,
            allow_profile=allow_profile,
        )
        if not comment:
            return web.json_response(
                {"ok": False, "error": "Комментарий не удалось добавить"},
                status=400,
            )
        getter = get_profile_generation_card if allow_profile else get_feed_generation_card
        card = await getter(
            gen_id,
            viewer_user_id=ctx["user"].id,
            include_unavailable=True,
        )
        return web.json_response(
            {
                "ok": True,
                "comment": comment,
                "comments_count": int((card or {}).get("comments_count") or 0),
            }
        )
    except Exception as e:
        return _miniapp_error_response(e, log_message="Mini App feed comment add failed")
''',
    )

    replace_once(
        path,
        '''        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]

        source = await get_feed_generation_card(gen_id, viewer_user_id=user.id)
        if not source or source.get("gen_type") != "image":
            return web.json_response({"ok": False, "error": "Пост ленты не найден"}, status=404)''',
        '''        telegram_id, ctx = await _get_user_context(request.app, init_data, body.get("start_param_fallback"))
        user = ctx["user"]
        allow_profile = str(body.get("surface", "feed") or "feed").strip().lower() == "profile"

        getter = get_profile_generation_card if allow_profile else get_feed_generation_card
        source = await getter(gen_id, viewer_user_id=user.id)
        if not source or source.get("gen_type") != "image":
            return web.json_response({"ok": False, "error": "Публикация не найдена"}, status=404)''',
    )


def patch_api() -> None:
    path = "frontend/miniapp-v0/lib/api.ts"
    replace_once(
        path,
        '''export async function likeFeedItem(genId: number): Promise<FeedItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed_item: FeedItem }>('feed/like', {
    init_data: initData,
    gen_id: genId,
  })
  return response.feed_item
}

export async function shareFeedItem(genId: number): Promise<{ item: FeedItem; link: string }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{
    ok: true
    feed_item: FeedItem
    link: string
    post_link?: string
    repeat_link?: string
    miniapp_link?: string
    miniapp_post_link?: string
    miniapp_repeat_link?: string
  }>('feed/share', {
    init_data: initData,
    gen_id: genId,
  })
  const isImage = String(response.feed_item?.gen_type || '').toLowerCase() === 'image'
  const preferredLink = isImage
    ? response.repeat_link || response.post_link || response.link
    : response.post_link || response.link
  return { item: response.feed_item, link: preferredLink }
}

export async function fetchFeedComments(genId: number, limit = 40): Promise<FeedComment[]> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; comments: FeedComment[] }>('feed/comments', {
    init_data: initData,
    gen_id: genId,
    limit,
  })
  return response.comments
}

export async function addFeedComment(
  genId: number,
  text: string
): Promise<{ comment: FeedComment; commentsCount: number }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; comment: FeedComment; comments_count: number }>('feed/comment', {
    init_data: initData,
    gen_id: genId,
    text,
  })
  return { comment: response.comment, commentsCount: response.comments_count }
}
''',
        '''export type FeedInteractionSurface = 'feed' | 'profile'

export async function likeFeedItem(
  genId: number,
  surface: FeedInteractionSurface = 'feed'
): Promise<FeedItem> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; feed_item: FeedItem }>('feed/like', {
    init_data: initData,
    gen_id: genId,
    surface,
  })
  return response.feed_item
}

export async function shareFeedItem(
  genId: number,
  surface: FeedInteractionSurface = 'feed'
): Promise<{ item: FeedItem; link: string; postLink: string; remixLink: string }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{
    ok: true
    feed_item: FeedItem
    link: string
    post_link?: string
    repeat_link?: string
    miniapp_link?: string
    miniapp_post_link?: string
    miniapp_repeat_link?: string
  }>('feed/share', {
    init_data: initData,
    gen_id: genId,
    surface,
  })
  const isImage = String(response.feed_item?.gen_type || '').toLowerCase() === 'image'
  const postLink =
    surface === 'profile'
      ? response.miniapp_post_link || response.miniapp_link || response.post_link || response.link
      : response.post_link || response.miniapp_post_link || response.link
  const remixLink =
    surface === 'profile'
      ? response.miniapp_repeat_link || response.repeat_link || postLink
      : response.repeat_link || response.miniapp_repeat_link || postLink
  const preferredLink = isImage ? remixLink : postLink
  return { item: response.feed_item, link: preferredLink, postLink, remixLink }
}

export async function fetchFeedComments(
  genId: number,
  limit = 40,
  surface: FeedInteractionSurface = 'feed'
): Promise<FeedComment[]> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; comments: FeedComment[] }>('feed/comments', {
    init_data: initData,
    gen_id: genId,
    limit,
    surface,
  })
  return response.comments
}

export async function addFeedComment(
  genId: number,
  text: string,
  surface: FeedInteractionSurface = 'feed'
): Promise<{ comment: FeedComment; commentsCount: number }> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }
  const response = await postJson<{ ok: true; comment: FeedComment; comments_count: number }>('feed/comment', {
    init_data: initData,
    gen_id: genId,
    text,
    surface,
  })
  return { comment: response.comment, commentsCount: response.comments_count }
}
''',
    )


def patch_profile() -> None:
    path = "frontend/miniapp-v0/components/tabs/profile-tab.tsx"
    text = read(path)
    text = text.replace(
        '''  fetchProfileFeed,
  saveProfileChannel,''',
        '''  fetchProfileFeed,
  likeFeedItem,
  saveProfileChannel,''',
        1,
    )
    text = text.replace("feedInteractionsEnabled", "profileInteractionsEnabled")
    old_helper = '''function profileInteractionsEnabled(item: FeedItem | null | undefined) {
  return Boolean(
    item &&
      item.feed_interactions_enabled !== false &&
      item.publication_scope !== 'profile'
  )
}'''
    new_helper = '''function profileInteractionsEnabled(item: FeedItem | null | undefined) {
  return Boolean(
    item &&
      item.publication_scope !== 'private' &&
      item.is_profile_visible !== false
  )
}'''
    if old_helper not in text:
        raise AssertionError("profile interaction helper anchor not found")
    text = text.replace(old_helper, new_helper, 1)
    text = text.replace(
        '''  const { state, viewedProfileCode, setActiveTab, setPromptPreset, setVideoPromptPreset } = useApp()''',
        '''  const {
    state,
    viewedProfileCode,
    feedDeepLink,
    consumeFeedDeepLink,
    setActiveTab,
    setPromptPreset,
    setVideoPromptPreset,
  } = useApp()''',
        1,
    )
    text = text.replace(
        '''  const [copied, setCopied] = useState<'profile' | number | null>(null)''',
        '''  const [copied, setCopied] = useState<string | number | null>(null)''',
        1,
    )
    text = text.replace(
        '''  async function copyText(text: string, marker: 'profile' | number) {''',
        '''  async function copyText(text: string, marker: string | number) {''',
        1,
    )
    text = text.replace(
        '''        const nextComments = await fetchFeedComments(commentsItem.id)''',
        '''        const nextComments = await fetchFeedComments(commentsItem.id, 40, 'profile')''',
        1,
    )
    text = text.replace(
        '''      const { comment, commentsCount } = await addFeedComment(commentsItem.id, text)''',
        '''      const { comment, commentsCount } = await addFeedComment(commentsItem.id, text, 'profile')''',
        1,
    )

    old_copy = '''  async function handleCopyPostLink(item: FeedItem) {
    if (!isLive || !profileInteractionsEnabled(item)) return
    setBusyId(item.id)
    try {
      const { item: updated, link } = await shareFeedItem(item.id)
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      await copyText(link, item.id)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось создать ссылку на пост'))
    } finally {
      setBusyId(null)
    }
  }
'''
    new_copy = '''  async function handleLike(item: FeedItem) {
    if (!isLive || !profileInteractionsEnabled(item)) return
    setBusyId(item.id)
    try {
      const updated = await likeFeedItem(item.id, 'profile')
      setItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      setCommentsItem((prev) => (prev?.id === updated.id ? updated : prev))
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось поставить лайк'))
    } finally {
      setBusyId(null)
    }
  }

  async function handleCopyPostLink(item: FeedItem, kind: 'post' | 'remix' = 'post') {
    if (!isLive || !profileInteractionsEnabled(item)) return
    setBusyId(item.id)
    try {
      const { item: updated, postLink, remixLink } = await shareFeedItem(item.id, 'profile')
      setItems((prev) => prev.map((feedItem) => (feedItem.id === updated.id ? updated : feedItem)))
      setPreviewItem((prev) => (prev?.id === updated.id ? updated : prev))
      const marker = kind === 'remix' ? `remix_${item.id}` : item.id
      await copyText(kind === 'remix' ? remixLink : postLink, marker)
    } catch (e) {
      setError(getErrorMessage(e, 'Не удалось создать ссылку на публикацию'))
    } finally {
      setBusyId(null)
    }
  }
'''
    if old_copy not in text:
        raise AssertionError("profile copy handler anchor not found")
    text = text.replace(old_copy, new_copy, 1)

    anchor = '''  useEffect(() => {
    const refreshProfileFeed = () => setFeedRefreshToken((value) => value + 1)
    window.addEventListener('banano:feed-changed', refreshProfileFeed)
    return () => window.removeEventListener('banano:feed-changed', refreshProfileFeed)
  }, [])
'''
    insertion = anchor + '''
  useEffect(() => {
    if (!isLive || !feedDeepLink || feedDeepLink.action !== 'preview') return
    if (feedDeepLink.item.publication_scope !== 'profile') return
    setItems((prev) => {
      const exists = prev.some((item) => item.id === feedDeepLink.item.id)
      return exists
        ? prev.map((item) => (item.id === feedDeepLink.item.id ? feedDeepLink.item : item))
        : [feedDeepLink.item, ...prev]
    })
    setPreviewItem(feedDeepLink.item)
    consumeFeedDeepLink()
  }, [consumeFeedDeepLink, feedDeepLink, isLive])
'''
    if anchor not in text:
        raise AssertionError("profile deep-link effect anchor not found")
    text = text.replace(anchor, insertion, 1)

    text = text.replace(
        '''                {!profileInteractionsEnabled(item) ? (
                  <span className="pointer-events-none absolute bottom-1 left-1/2 -translate-x-1/2 rounded bg-background/85 px-1.5 py-0.5 text-[9px] font-semibold text-cyan backdrop-blur">
                    Только профиль
                  </span>
                ) : null}''',
        '''                {item.publication_scope === 'profile' ? (
                  <span className="pointer-events-none absolute bottom-1 left-1/2 -translate-x-1/2 rounded bg-background/85 px-1.5 py-0.5 text-[9px] font-semibold text-cyan backdrop-blur">
                    Только профиль
                  </span>
                ) : null}''',
        1,
    )

    old_bottom = '''          <div className="absolute bottom-4 left-3 right-3 flex justify-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive || !profileInteractionsEnabled(previewItem)}
              onClick={() => setCommentsItem(previewItem)}
            >
              <MessageCircle className="h-4 w-4" />
              {previewItem.comments_count || 0}
            </Button>
            {previewItem.can_blur || previewItem.is_mine ? (
              <Button
                type="button"
                variant="secondary"
                className="h-10 rounded-full px-4"
                disabled={!isLive || previewItem.is_adult_content || busyId === previewItem.id}
                onClick={() => handleToggleBlur(previewItem)}
              >
                {previewItem.feed_blurred ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                <span>
                  {previewItem.is_adult_content
                    ? 'Blur обязателен для 18+'
                    : previewItem.feed_blurred
                      ? 'Убрать blur'
                      : 'Blur'}
                </span>
              </Button>
            ) : null}
            <Button
              type="button"
              className="h-10 rounded-full px-4"
              disabled={!profileInteractionsEnabled(previewItem)}
              onClick={() => handleRemix(previewItem)}
            >
              <Repeat2 className="h-4 w-4" />
              <span>Повторить</span>
            </Button>

          </div>'''
    new_bottom = '''          <div className="absolute bottom-4 left-3 right-3 flex flex-wrap justify-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive || busyId === previewItem.id || !profileInteractionsEnabled(previewItem)}
              onClick={() => handleLike(previewItem)}
            >
              <Heart className="h-4 w-4" />
              {previewItem.likes_count || 0}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full bg-secondary/90 px-4"
              disabled={!isLive || !profileInteractionsEnabled(previewItem)}
              onClick={() => setCommentsItem(previewItem)}
            >
              <MessageCircle className="h-4 w-4" />
              {previewItem.comments_count || 0}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="h-10 rounded-full px-4"
              disabled={!isLive || busyId === previewItem.id || !profileInteractionsEnabled(previewItem)}
              onClick={() => handleCopyPostLink(previewItem, 'post')}
            >
              {copied === previewItem.id ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
              <span>{copied === previewItem.id ? 'Скопировано' : 'Поделиться'}</span>
            </Button>
            {previewItem.gen_type === 'image' ? (
              <Button
                type="button"
                variant="secondary"
                className="h-10 rounded-full px-4"
                disabled={!isLive || busyId === previewItem.id || !profileInteractionsEnabled(previewItem)}
                onClick={() => handleCopyPostLink(previewItem, 'remix')}
              >
                {copied === `remix_${previewItem.id}` ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
                <span>{copied === `remix_${previewItem.id}` ? 'Скопировано' : 'Ссылка ремикса'}</span>
              </Button>
            ) : null}
            {previewItem.can_blur || previewItem.is_mine ? (
              <Button
                type="button"
                variant="secondary"
                className="h-10 rounded-full px-4"
                disabled={!isLive || previewItem.is_adult_content || busyId === previewItem.id}
                onClick={() => handleToggleBlur(previewItem)}
              >
                {previewItem.feed_blurred ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                <span>
                  {previewItem.is_adult_content
                    ? 'Blur обязателен для 18+'
                    : previewItem.feed_blurred
                      ? 'Убрать blur'
                      : 'Blur'}
                </span>
              </Button>
            ) : null}
            <Button
              type="button"
              className="h-10 rounded-full px-4"
              disabled={!profileInteractionsEnabled(previewItem)}
              onClick={() => handleRemix(previewItem)}
            >
              <Repeat2 className="h-4 w-4" />
              <span>Повторить</span>
            </Button>
          </div>'''
    if old_bottom not in text:
        raise AssertionError("profile preview action bar anchor not found")
    text = text.replace(old_bottom, new_bottom, 1)
    write(path, text)


def patch_context() -> None:
    path = "frontend/miniapp-v0/lib/app-context.tsx"
    replace_once(
        path,
        '''        if (startTarget.kind === 'feed' || startTarget.kind === 'remix') {
          const item = await fetchFeedItem(startTarget.genId)
          if (cancelled) return
          if (startTarget.kind === 'remix') {
            applyFeedRemix(item)
            return
          }
          setFeedDeepLink({ item, action: 'preview' })
          setActiveTabState(4)
          return
        }''',
        '''        if (startTarget.kind === 'feed' || startTarget.kind === 'remix') {
          const item = await fetchFeedItem(startTarget.genId)
          if (cancelled) return
          if (startTarget.kind === 'remix') {
            applyFeedRemix(item)
            return
          }
          setFeedDeepLink({ item, action: 'preview' })
          if (item.publication_scope === 'profile') {
            setViewedProfileCode(String(item.author_referral_code || '').trim().toUpperCase() || null)
            setActiveTabState(7)
          } else {
            setActiveTabState(4)
          }
          return
        }''',
    )


def patch_tests() -> None:
    path = "tests/test_database.py"
    text = read(path)
    text = text.replace('''    assert card["feed_interactions_enabled"] is False''', '''    assert card["feed_interactions_enabled"] is True''', 2)
    marker = '''@pytest.mark.asyncio
async def test_feed_publication_is_visible_in_feed_and_profile'''
    if marker not in text:
        raise AssertionError("database test insertion marker not found")
    test = '''@pytest.mark.asyncio
async def test_profile_only_interactions_require_profile_context(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "profile_interactions.db"))
    await database.init_db()
    author = await database.get_or_create_user(440010)
    viewer = await database.get_or_create_user(440011)
    await database.add_generation_task(
        author.id,
        author.telegram_id,
        "profile-interactions-task",
        "image",
        "banana_pro",
        model="banana_pro",
        aspect_ratio="1:1",
        prompt="profile interaction test",
        cost=2,
    )
    await database.complete_video_task(
        "profile-interactions-task",
        "https://example.com/profile-interactions.png",
    )
    card = await database.share_to_feed(
        "profile-interactions-task",
        author.id,
        publication_scope="profile",
    )

    assert await database.like_feed_generation(card["id"], viewer.id) is None
    assert await database.increment_feed_share(card["id"]) is None
    assert await database.add_feed_comment(card["id"], viewer.id, "hidden") is None

    liked = await database.like_feed_generation(
        card["id"],
        viewer.id,
        allow_profile=True,
    )
    shared = await database.increment_feed_share(card["id"], allow_profile=True)
    comment = await database.add_feed_comment(
        card["id"],
        viewer.id,
        "Работает в профиле",
        allow_profile=True,
    )

    assert liked is not None
    assert liked["publication_scope"] == "profile"
    assert liked["likes_count"] == 1
    assert shared is not None
    assert shared["shares_count"] == 1
    assert comment is not None
    assert comment["text"] == "Работает в профиле"
    comments = await database.get_feed_comments(card["id"], viewer_user_id=viewer.id)
    assert [item["text"] for item in comments] == ["Работает в профиле"]
    assert await database.get_feed_generations(limit=20) == []


'''
    text = text.replace(marker, test + marker, 1)
    write(path, text)


def patch_docs() -> None:
    path = "tracemap_feed_referral.md"
    text = read(path)
    old = "-> likes/shares/comments/remix remain available only for general-feed publications"
    new = "-> profile-only likes/comments/shares/remix are available from the author profile; the general feed still never lists the publication"
    if old in text:
        text = text.replace(old, new, 1)
    write(path, text)


def main() -> None:
    patch_database()
    patch_miniapp()
    patch_api()
    patch_profile()
    patch_context()
    patch_tests()
    patch_docs()
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()

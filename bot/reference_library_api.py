"""Authenticated personal-library API. No caller-supplied owner IDs."""

from aiohttp import web

from bot import database, reference_library


async def reference_library_action(request):
    from bot import miniapp

    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise TypeError("Неверный запрос")
        telegram_id, _ = await miniapp._get_user_context(request.app, body.get('init_data', ''))
        action = body.get('action', 'categories')
        category = body.get('category_id')
        if action == 'categories':
            recent = await database.list_saved_references(telegram_id, kind=body.get('kind'), limit=24)
            return web.json_response({'ok': True, 'categories': await reference_library.list_categories(telegram_id),
                                      'recent': [reference_library.reference_payload(item) for item in recent]})
        if action == 'create_category':
            result = await reference_library.create_category(telegram_id, body.get('name'))
            return web.json_response({'ok': True, 'category': result})
        if action == 'rename_category':
            await reference_library.rename_category(telegram_id, category, body.get('name'))
        elif action == 'delete_category':
            await reference_library.delete_category(telegram_id, category)
        elif action == 'items':
            offset = int(body.get('offset') or 0)
            items = await reference_library.list_items(telegram_id, category, kind=body.get('kind'), offset=offset)
            return web.json_response({'ok': True, 'items': items, 'next_offset': offset + 40 if len(items) == 40 else None})
        elif action in {'save_item', 'remove_item'}:
            raw_id = str(body.get('reference_id') or '')
            if not raw_id.isdigit() or not 0 < int(raw_id) < 2 ** 63:
                raise ValueError('Неверный референс')
            if action == 'save_item':
                await reference_library.save_item(telegram_id, category, int(raw_id), body.get('title'))
            else:
                await reference_library.remove_item(telegram_id, category, int(raw_id))
        else:
            raise ValueError('Неизвестное действие')
        return web.json_response({'ok': True})
    except PermissionError as exc:
        return web.json_response({'ok': False, 'error': str(exc)}, status=403)
    except (ValueError, TypeError) as exc:
        return web.json_response({'ok': False, 'error': str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - shared HTTP error boundary
        return miniapp._miniapp_error_response(exc, log_message='Personal reference library failed')

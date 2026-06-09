from pathlib import Path

path = Path('/root/banano_kling/bot/handlers/admin.py')
text = path.read_text(encoding='utf-8')
old = '''    await callback.message.edit_text(
        f"📢 <b>Рассылка завершена!</b>

"
        f"✅ Успешно: <code>{success_count}</code>
"
        f"❌ Ошибок: <code>{error_count}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )
'''
# broken literal tolerant replacement by slicing
start = text.index('    await callback.message.edit_text(', text.index('    for user in users:'))
end = text.index('    await state.clear()', start)
replacement = r'''    await callback.message.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: <code>{success_count}</code>\n"
        f"❌ Ошибок: <code>{error_count}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )

'''
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding='utf-8')
print('fixed broadcast confirm tail')

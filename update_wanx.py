#!/usr/bin/env python3
import re

with open("bot/handlers/generation.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the WanX txt2video + LoRA section and replace with enhanced version
old_section = """        # WanX txt2video + LoRA
        if v_model.startswith("wanx"):
            wanx_loras = data.get("wanx_lora_settings") or [
                {"lora_type": "nsfw-general", "lora_strength": 1.0}
            ]
            result = await wanx_service.generate_txt2video_lora(
                prompt=prompt,
                aspect_ratio=v_ratio,
                lora_settings=wanx_loras,
                webhook_url=config.wanx_notification_url
                if config.WEBHOOK_HOST
                else None,
            )"""

new_section = """        # WanX txt2video + LoRA или img2video + LoRA
        if v_model.startswith("wanx"):
            wanx_loras = data.get("wanx_lora_settings") or [
                {"lora_type": "nsfw-general", "lora_strength": 1.0}
            ]
            # Если есть загруженное изображение для режима imgtxt, используем img2video
            if v_type == "imgtxt" and v_image_url:
                # Загружаем изображение из URL или файла
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        async with session.get(v_image_url) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                            else:
                                # Пытаемся прочитать локальный файл
                                import os
                                if os.path.exists(v_image_url.replace(config.static_base_url, "static").lstrip('/')):
                                    with open(v_image_url.replace(config.static_base_url, "static").lstrip('/'), 'rb') as f:
                                        image_bytes = f.read()
                                else:
                                    # Если не удалось получить изображение, fallback на txt2video
                                    logger.warning(f"Failed to load image for WanX img2video, falling back to txt2video")
                                    result = await wanx_service.generate_txt2video_lora(
                                        prompt=prompt,
                                        aspect_ratio=v_ratio,
                                        lora_settings=wanx_loras,
                                        webhook_url=config.wanx_notification_url
                                        if config.WEBHOOK_HOST
                                        else None,
                                    )
                except Exception as e:
                    logger.error(f"Error loading image for WanX img2video: {e}")
                    # Fallback на txt2video
                    result = await wanx_service.generate_txt2video_lora(
                        prompt=prompt,
                        aspect_ratio=v_ratio,
                        lora_settings=wanx_loras,
                        webhook_url=config.wanx_notification_url
                        if config.WEBHOOK_HOST
                        else None,
                    )
                else:
                    # Используем img2video с изображением
                    result = await wanx_service.generate_img2video_lora(
                        image_bytes=image_bytes,
                        prompt=prompt,
                        aspect_ratio=v_ratio,
                        lora_settings=wanx_loras,
                        webhook_url=config.wanx_notification_url
                        if config.WEBHOOK_HOST
                        else None,
                    )
            else:
                # Стандартный txt2video
                result = await wanx_service.generate_txt2video_lora(
                    prompt=prompt,
                    aspect_ratio=v_ratio,
                    lora_settings=wanx_loras,
                    webhook_url=config.wanx_notification_url
                    if config.WEBHOOK_HOST
                    else None,
                )"""

if old_section in content:
    content = content.replace(old_section, new_section)
    with open("bot/handlers/generation.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Successfully updated WanX section for img2video support")
else:
    print("Old section not found, trying alternative pattern...")
    # Try another pattern
    old_section_alt = """        # WanX txt2video + LoRA
        if v_model.startswith("wanx"):
            wanx_loras = data.get("wanx_lora_settings") or [
                {"lora_type": "nsfw-general", "lora_strength": 1.0}
            ]
            result = await wanx_service.generate_txt2video_lora(
                prompt=prompt,
                aspect_ratio=v_ratio,
                lora_settings=wanx_loras,
                webhook_url=config.wanx_notification_url
                if config.WEBHOOK_HOST
                else None,
            )"""
    if old_section_alt in content:
        content = content.replace(old_section_alt, new_section)
        with open("bot/handlers/generation.py", "w", encoding="utf-8") as f:
            f.write(content)
        print("Successfully updated WanX section (alternative pattern)")
    else:
        print("Could not find WanX section to replace")
        # Print context to debug
        import re

        matches = re.findall(
            r"# WanX txt2video.*?result = await wanx_service\.generate_txt2video_lora.*?\)",
            content,
            re.DOTALL,
        )
        print(f"Found {len(matches)} matches")
        for i, match in enumerate(matches):
            print(f"Match {i}: {match[:200]}...")

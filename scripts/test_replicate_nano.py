#!/usr/bin/env python3
import asyncio
import os
import sys

sys.path.insert(0, "/root/vkbanana/bot/banano_kling")

from bot.services.replicate_service import replicate_service


async def test_nano():
    placeholder_url = "https://vkkling.chillcreative.ru/uploads/20260407/304b9448.png"
    result = await replicate_service.generate_nano_banana(
        prompt="Transform this test image into a cyberpunk cityscape at night",
        image_input_uris=[placeholder_url],
        aspect_ratio="1:1",
        resolution="1K",
        user_id="test_user",
    )
    print("Result:", result)


asyncio.run(test_nano())

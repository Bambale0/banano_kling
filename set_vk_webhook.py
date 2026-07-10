#!/usr/bin/env python3
import os

from dotenv import load_dotenv

load_dotenv()

import httpx

token = os.getenv("VK_GROUP_TOKEN")
group_id = os.getenv("VK_GROUP_ID")
webhook_url = "https://vkkling.chillcreative.ru/webhook"
secret = os.getenv("VK_SECRET_KEY", "")

resp = httpx.post(
    "https://api.vk.com/method/groups.setCallbackServer",
    data={
        "group_id": group_id,
        "url": webhook_url,
        "title": "Banano Kling Webhook",
        "secret_key": secret,
        "v": "5.199",
        "access_token": token,
    },
)
print(resp.json())

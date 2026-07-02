#!/usr/bin/env python3
"""Fix the duplicate upload_url_to_kie line."""
with open("vk_bot_lp.py", "r") as f:
    lines = f.readlines()

fixed = []
skip = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if i == 1306 and stripped == "async def upload_url_to_kie" and not stripped.endswith("("):
        skip = True
        continue
    if skip and stripped == "async def upload_url_to_kie(":
        skip = False
        fixed.append(line)
        continue
    fixed.append(line)

with open("vk_bot_lp.py", "w") as f:
    f.writelines(fixed)
print("Fix applied")

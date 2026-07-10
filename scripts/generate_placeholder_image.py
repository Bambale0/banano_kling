#!/usr/bin/env python3
"""Generate a local placeholder test image (PNG) for Nano Banana test runs."""

import os
import uuid
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont


def main():
    date_str = datetime.now().strftime("%Y%m%d")
    upload_dir = os.path.join("static", "uploads", date_str)
    os.makedirs(upload_dir, exist_ok=True)

    file_id = str(uuid.uuid4())[:8]
    filename = f"{file_id}.png"
    filepath = os.path.join(upload_dir, filename)

    # Create an image with a simple text
    img = Image.new("RGB", (1024, 1024), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except Exception:
        font = ImageFont.load_default()

    text = "Nano Banana 2 - Test"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Use textbbox for Pillow versions where textsize is not available
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except Exception:
        try:
            w, h = font.getsize(text)
        except Exception:
            w, h = (len(text) * 10, 40)

    draw.text(((1024 - w) / 2, 420), text, font=font, fill=(255, 200, 0))

    try:
        bbox2 = draw.textbbox((0, 0), timestamp, font=font)
        w2 = bbox2[2] - bbox2[0]
        h2 = bbox2[3] - bbox2[1]
    except Exception:
        try:
            w2, h2 = font.getsize(timestamp)
        except Exception:
            w2, h2 = (len(timestamp) * 8, 20)

    draw.text(((1024 - w2) / 2, 480), timestamp, font=font, fill=(200, 200, 200))

    img.save(filepath, format="PNG")
    print(filepath)


if __name__ == "__main__":
    main()

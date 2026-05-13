import os
import time
from pathlib import Path

from scripts.cleanup_uploads import cleanup_uploads


def test_cleanup_uploads_deletes_old_images_and_keeps_recent_video(tmp_path):
    old_img = tmp_path / "old.jpg"
    recent_video = tmp_path / "recent.mp4"
    unknown = tmp_path / "note.txt"
    old_img.write_bytes(b"x" * 10)
    recent_video.write_bytes(b"v" * 10)
    unknown.write_text("keep")
    old = time.time() - 48 * 3600
    os.utime(old_img, (old, old))

    stats = cleanup_uploads(tmp_path, image_hours=24, video_hours=24 * 7, dry_run=False)

    assert stats["deleted"] == 1
    assert not old_img.exists()
    assert recent_video.exists()
    assert unknown.exists()

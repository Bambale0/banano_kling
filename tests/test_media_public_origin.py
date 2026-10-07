from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bot.genjutsu.media import MediaStore


def test_frontend_installer_preserves_signed_genjutsu_proxy():
    source = Path("scripts/install_miniapp_frontend_host.sh").read_text()
    # Both generated server variants must keep the existing production route.
    assert source.count("location ^~ /genjutsu/ {") == 2


def test_genjutsu_media_and_callback_urls_use_public_media_origin(tmp_path):
    origin = "https://tanyapp.xn--e1aikcel5c5a.online"
    media = MediaStore(tmp_path, origin, "synthetic-test-key-never-used-in-production")
    asset_url = urlsplit(media.url("synthetic-asset", ttl=60, now=1000))
    assert f"{asset_url.scheme}://{asset_url.netloc}" == origin
    assert asset_url.path == "/genjutsu/media/synthetic-asset"
    query = parse_qs(asset_url.query)
    assert media.verify("synthetic-asset", query["expires"][0], query["signature"][0], now=1000)
    callback_url = urlsplit(media.callback_url("synthetic-step", "1", ttl=60))
    assert f"{callback_url.scheme}://{callback_url.netloc}" == origin
    assert callback_url.path == "/genjutsu/callback/synthetic-step/1"
    query = parse_qs(callback_url.query)
    assert media.verify_callback("synthetic-step", "1", query["expires"][0], query["signature"][0])

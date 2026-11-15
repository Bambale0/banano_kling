"""Non-hydrating media checks for owner history previews."""
from types import SimpleNamespace

import pytest

from bot import database
from bot.services import media_input_utils, media_storage


@pytest.mark.parametrize("presence,visible", [(True, True), (False, False), (None, True)])
def test_owner_history_preserves_url_without_s3_download(monkeypatch, presence, visible):
    url = "https://tanyapp.chillcreative.ru/uploads/result.jpg"
    monkeypatch.setattr(media_input_utils, "is_local_upload_source", lambda source: source == url)
    monkeypatch.setattr(
        media_input_utils, "local_upload_presence_without_download", lambda source: presence,
    )

    def fail_if_hydrated(_source):
        raise AssertionError("history must not materialize uploads")

    monkeypatch.setattr(media_input_utils, "resolve_local_upload_path", fail_if_hydrated)
    row = {"result_url": url, "result_urls": "[]", "created_at": None}

    resolved = database.resolve_public_generation_result_urls(
        row, hydrate_local_uploads=False,
    )
    assert resolved == ([url] if visible else [])


def test_history_s3_head_is_read_only_and_distinguishes_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(media_storage, "local_upload_path", lambda relative: tmp_path / relative)
    monkeypatch.setattr(media_storage, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(
        media_storage.S3Settings, "from_config",
        classmethod(lambda cls: SimpleNamespace(bucket="test", endpoint="https://example.test")),
    )
    monkeypatch.setattr(media_storage, "object_key", lambda relative, settings: relative)
    monkeypatch.setattr(media_storage, "_missing_cached", lambda settings, key: False)
    monkeypatch.setattr(media_storage, "_remember_missing", lambda settings, key: None)
    monkeypatch.setattr(media_storage, "_forget_missing", lambda settings, key: None)

    class Client:
        error = None
        calls = []

        def head_object(self, **kwargs):
            self.calls.append(kwargs)
            if self.error:
                raise self.error

        def download_file(self, *args, **kwargs):
            raise AssertionError("history must never download S3 objects")

    client = Client()
    monkeypatch.setattr(media_storage, "_s3_client", lambda settings: client)
    assert media_storage.upload_presence_without_download("result.jpg") is True

    class Missing(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    client.error = Missing()
    assert media_storage.upload_presence_without_download("missing.jpg") is False
    client.error = RuntimeError("temporary outage")
    assert media_storage.upload_presence_without_download("unknown.jpg") is None
    assert len(client.calls) == 3


def test_history_media_rejects_parent_traversal():
    with pytest.raises(ValueError):
        media_storage.upload_presence_without_download("../secret")

"""A failed media check must not advertise a missing saved reference."""
from types import SimpleNamespace

from bot import database
from bot.services import media_input_utils


def test_saved_reference_check_failure_is_unavailable(monkeypatch):
    monkeypatch.setattr(media_input_utils, "is_local_upload_source", lambda _: True)

    def broken_resolver(_):
        raise OSError("media volume unavailable")

    monkeypatch.setattr(media_input_utils, "resolve_local_upload_path", broken_resolver)
    ref = SimpleNamespace(file_url="/uploads/refs/missing.png")
    assert database._saved_reference_is_available(ref) is False


def test_saved_reference_remote_url_does_not_require_local_file(monkeypatch):
    monkeypatch.setattr(media_input_utils, "is_local_upload_source", lambda _: False)
    ref = SimpleNamespace(file_url="https://example.test/image.png")
    assert database._saved_reference_is_available(ref) is True

import hashlib
from pathlib import Path

from scripts import migrate_media_to_s3 as migration


def test_media_migration_dry_run_never_uploads(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "refs/image/42/face.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    monkeypatch.setattr(migration, "remote_upload_fingerprint", lambda _relative: None)
    monkeypatch.setattr(
        migration,
        "persist_upload_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not upload")),
    )

    result = migration.migrate_one(source, root=root, dry_run=True, verify_only=False)

    assert result.status == "planned"
    assert result.relative_path == "refs/image/42/face.png"


def test_media_migration_skips_verified_object(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "feed/result.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    monkeypatch.setattr(
        migration, "remote_upload_fingerprint",
        lambda _relative: (5, hashlib.sha256(b"video").hexdigest()),
    )
    monkeypatch.setattr(
        migration,
        "persist_upload_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not upload")),
    )

    result = migration.migrate_one(source, root=root, dry_run=False, verify_only=False)

    assert result.status == "verified"


def test_media_migration_uploads_and_verifies_size(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "trend-assets/image/aa/file.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"asset")
    fingerprints = iter([None, (5, hashlib.sha256(b"asset").hexdigest())])
    monkeypatch.setattr(migration, "remote_upload_fingerprint", lambda _relative: next(fingerprints))
    calls = []
    monkeypatch.setattr(
        migration,
        "persist_upload_file",
        lambda relative, path, **kwargs: calls.append((relative, Path(path), kwargs))
        or "https://media.test/uploads/" + relative,
    )

    result = migration.migrate_one(source, root=root, dry_run=False, verify_only=False)

    assert result.status == "uploaded"
    assert calls[0][0] == "trend-assets/image/aa/file.png"
    assert calls[0][2]["cache_control"] == "private, max-age=0"
    assert calls[0][2]["retain_local_copy"] is True


def test_media_migration_ignores_temporary_and_symlink_files(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "good.jpg").write_bytes(b"ok")
    (root / "bad.part").write_bytes(b"partial")
    (root / "bad.tmp").write_bytes(b"temporary")
    (root / "link.jpg").symlink_to(root / "good.jpg")

    assert [path.name for path in migration.iter_source_files(root)] == ["good.jpg"]


def test_media_migration_does_not_copy_local_cache_markers(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "result.jpg").write_bytes(b"ok")
    (root / ".result.jpg.s3-cache").write_text("metadata only")

    assert [path.name for path in migration.iter_source_files(root)] == ["result.jpg"]


def test_migration_reuploads_remote_object_with_equal_size_but_no_checksum(monkeypatch, tmp_path):
    from tests.test_media_storage import FakeS3Client, configure_s3

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    source = tmp_path / "uploads/feed/replace.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"good")
    fake.objects[("neuromix-media", "uploads/feed/replace.jpg")] = b"evil"

    planned = migration.migrate_one(source, root=tmp_path / "uploads", dry_run=True, verify_only=False)

    assert planned.status == "planned"


def test_migration_scheduler_caps_prefetched_files(monkeypatch, tmp_path):
    import threading
    import time

    root = tmp_path / "uploads"
    root.mkdir()
    completed = threading.Event()
    consumed = 0

    def streaming_paths():
        nonlocal consumed
        for index in range(40):
            consumed += 1
            if consumed > 8 and not completed.is_set():
                raise AssertionError("too many scheduled before first result")
            yield root / f"item-{index}.png"

    def run_one(path, *, root, dry_run, verify_only):
        time.sleep(0.005)
        completed.set()
        return migration.MigrationResult(path.name, 1, "planned")

    monkeypatch.setattr(migration, "migrate_one", run_one)
    results = list(migration.iter_migration_results(
        streaming_paths(),
        root=root,
        workers=2,
        dry_run=True,
        verify_only=False,
    ))
    assert len(results) == 40
    assert consumed == 40

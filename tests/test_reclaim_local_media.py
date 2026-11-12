import hashlib

from scripts import reclaim_local_media as reclaim


def test_reclaim_is_dry_run_by_default(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "feed/result.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    monkeypatch.setattr(
        reclaim, "remote_upload_fingerprint",
        lambda _relative: (5, hashlib.sha256(b"video").hexdigest()),
    )

    result = reclaim.reclaim_one(source, root=root, execute=False)

    assert result.status == "reclaimable"
    assert source.read_bytes() == b"video"


def test_reclaim_blocks_missing_or_mismatched_s3_object(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "refs/image/42/face.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    monkeypatch.setattr(reclaim, "remote_upload_fingerprint", lambda _relative: None)

    result = reclaim.reclaim_one(source, root=root, execute=True)

    assert result.status == "blocked"
    assert source.exists()


def test_reclaim_deletes_only_exact_size_verified_copy(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "refs/image/42/face.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    marker = source.with_name(f".{source.name}.s3-cache")
    marker.touch()
    monkeypatch.setattr(
        reclaim, "remote_upload_fingerprint",
        lambda _relative: (5, hashlib.sha256(b"image").hexdigest()),
    )

    result = reclaim.reclaim_one(source, root=root, execute=True)

    assert result.status == "deleted"
    assert not source.exists()
    assert not marker.exists()


def test_reclaim_cli_requires_exact_bucket_confirmation(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(reclaim, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(
        reclaim.S3Settings,
        "from_config",
        classmethod(lambda _cls: type("Settings", (), {"bucket": "media-prod"})()),
    )

    exit_code = reclaim.main(
        [
            "--root",
            str(root),
            "--execute",
            "--confirm-bucket",
            "wrong-bucket",
        ]
    )

    assert exit_code == 2


def test_reclaim_refuses_equal_size_nonverified_content(monkeypatch, tmp_path):
    from tests.test_media_storage import FakeS3Client, configure_s3

    monkeypatch.chdir(tmp_path)
    fake = FakeS3Client()
    configure_s3(monkeypatch, fake)
    root = tmp_path / "uploads"
    source = root / "refs/image/face.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"good")
    fake.objects[("neuromix-media", "uploads/refs/image/face.jpg")] = b"evil"

    result = reclaim.reclaim_one(source, root=root, execute=True)

    assert result.status == "blocked"
    assert source.read_bytes() == b"good"


def test_reclaim_skips_recent_file_before_remote_head(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "refs/image/recent.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"recent")

    def unexpected_remote(_relative):
        raise AssertionError("Recently changed media must not be touched")

    monkeypatch.setattr(reclaim, "remote_upload_fingerprint", unexpected_remote)
    result = reclaim.reclaim_one(
        source, root=root, execute=True, min_age_seconds=86400
    )
    assert result.status == "skipped"
    assert source.read_bytes() == b"recent"


def test_reclaim_streams_limited_catalog_and_journals(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    source = root / "feed/old.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"verified")
    digest = hashlib.sha256(b"verified").hexdigest()

    monkeypatch.setattr(reclaim, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(
        reclaim.S3Settings,
        "from_config",
        classmethod(lambda _cls: type("Settings", (), {"bucket": "media-prod"})()),
    )
    monkeypatch.setattr(
        reclaim, "remote_upload_fingerprint", lambda _relative: (8, digest)
    )

    def generator(_root, _prefixes):
        yield source
        raise AssertionError("CLI loaded beyond --limit into memory")

    monkeypatch.setattr(reclaim, "iter_source_files", generator)
    manifest = tmp_path / "audit.jsonl"
    code = reclaim.main([
        "--root", str(root), "--limit", "1", "--min-age-seconds", "0",
        "--manifest", str(manifest), "--quiet",
    ])
    assert code == 0
    assert source.read_bytes() == b"verified"
    import json

    record = json.loads(manifest.read_text().strip())
    assert record["status"] == "reclaimable"
    assert record["relative_path"] == "feed/old.jpg"


def test_execute_requires_manifest(monkeypatch, tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(reclaim, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(
        reclaim.S3Settings,
        "from_config",
        classmethod(lambda _cls: type("Settings", (), {"bucket": "media-prod"})()),
    )
    assert reclaim.main([
        "--root", str(root), "--execute", "--confirm-bucket", "media-prod"
    ]) == 2

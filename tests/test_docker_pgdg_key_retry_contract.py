"""Production Docker image must tolerate transient PGDG key transport failures."""
from pathlib import Path


def test_postgresql_signing_key_transport_is_bounded_and_retried():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8",
    )
    assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in dockerfile
    key_install = dockerfile.split("&& curl --fail --silent --show-error", 1)[1]
    key_install = key_install.split("&& . /etc/os-release", 1)[0]
    assert "--http1.1" in key_install
    assert "--retry 5" in key_install
    assert "--retry-all-errors" in key_install
    assert "--connect-timeout 15" in key_install
    assert "--max-time 60" in key_install


def test_postgresql_client_version_and_apt_signature_stay_enforced():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8",
    )
    assert "Signed-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc" in dockerfile
    assert "postgresql-client-16" in dockerfile
    assert "pg_dump --version | grep -Eq 'pg_dump \\(PostgreSQL\\) 16\\.'" in dockerfile
    assert dockerfile.count("Acquire::Retries=5") >= 2

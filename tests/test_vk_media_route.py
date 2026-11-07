"""Exercise the production installer without touching Nginx or production files."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "vk_media_route", ROOT / "scripts/configure_vk_media_route.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)

SITE = """server {
    listen 80;
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 443 ssl;
    # Preserve TLS, CSP and private API configuration verbatim.
    location ^~ /mini-app/api/ {
        proxy_pass http://127.0.0.1:1888;
        proxy_set_header Host $host;
    }
    location / { try_files $uri $uri/ /index.html; }
}
"""


@pytest.fixture
def files(tmp_path):
    site = tmp_path / "site.conf"
    site.write_text(SITE)
    return site, tmp_path / "media.conf"


def test_installs_upload_proxy_before_spa_and_preserves_existing_config(files):
    site, snippet = files
    calls = []
    installer.configure(site, snippet, run=lambda args: calls.append(args))
    include = f'    include "{snippet.as_posix()}";\n'
    assert site.read_text().replace(include, "", 1) == SITE
    assert site.read_text().index(include) < site.read_text().rindex("location / {")
    assert "location ^~ /uploads/" in snippet.read_text()
    assert "proxy_pass http://127.0.0.1:1888;" in snippet.read_text()
    assert "Cache-Control" not in snippet.read_text()
    assert calls == [["nginx", "-t"], ["systemctl", "reload", "nginx"]]
    installer.configure(site, snippet, run=lambda args: calls.append(args))
    assert calls == [["nginx", "-t"], ["systemctl", "reload", "nginx"]]


@pytest.mark.parametrize("failure", ["validate", "reload"])
@pytest.mark.parametrize("existing_snippet", [False, True])
def test_failed_validation_or_reload_restores_both_files(files, failure, existing_snippet):
    site, snippet = files
    if existing_snippet:
        snippet.write_text("# previous managed fragment\n")
    calls = []

    def run(args):
        calls.append(args)
        if len(calls) == (1 if failure == "validate" else 2):
            raise subprocess.CalledProcessError(1, args)

    with pytest.raises(subprocess.CalledProcessError):
        installer.configure(site, snippet, run=run)
    assert site.read_text() == SITE
    if existing_snippet:
        assert snippet.read_text() == "# previous managed fragment\n"
    else:
        assert not snippet.exists()
    if failure == "reload":
        assert calls[-2:] == [["nginx", "-t"], ["systemctl", "reload", "nginx"]]


def test_uses_actual_api_upstream_and_updates_existing_managed_include(files):
    site, snippet = files
    site.write_text(SITE.replace(":1888", ":2888"))
    installer.configure(site, snippet, run=lambda args: None)
    assert "proxy_pass http://127.0.0.1:2888;" in snippet.read_text()
    site.write_text(site.read_text().replace(":2888", ":3888"))
    installer.configure(site, snippet, run=lambda args: None)
    assert "proxy_pass http://127.0.0.1:3888;" in snippet.read_text()
    assert site.read_text().count(f'include "{snippet.as_posix()}";') == 1


@pytest.mark.parametrize("source", [
    SITE.replace("http://127.0.0.1:1888", "http://$backend"),
    SITE.replace("location / { try_files", "location /app/ { try_files"),
    SITE.replace("location / { try_files", "location /uploads/ { return 403; }\n    location / { try_files"),
    SITE.replace("location / { try_files", "location ~* /uploads/private/ { return 403; }\n    location / { try_files"),
    SITE.replace("location / { try_files", "location ~ ^/uploads(?:/|$) { return 403; }\n    location / { try_files"),
])
def test_unknown_or_custom_routing_fails_without_changes(files, source):
    site, snippet = files
    site.write_text(source)
    with pytest.raises(ValueError):
        installer.configure(site, snippet, run=lambda args: pytest.fail("No reload"))
    assert site.read_text() == source
    assert not snippet.exists()


def test_normal_frontend_deploy_installs_route_before_publishing():
    deploy = (ROOT / "scripts/deploy_miniapp_local.sh").read_text()
    assert deploy.index("configure_vk_media_route.py") < deploy.index('log "Publishing static export')
    assert deploy.index("configure_vk_media_route.py") < deploy.index('if [[ -f "${MINIAPP_ROOT}/index.html" ]]')


def test_cross_server_api_and_spa_are_rejected_without_changes(files):
    site, snippet = files
    source = SITE.replace("    location / { try_files", "}\nserver {\n    location / { try_files")
    site.write_text(source)
    with pytest.raises(ValueError):
        installer.configure(site, snippet, run=lambda args: pytest.fail("No reload"))
    assert site.read_text() == source
    assert not snippet.exists()


def test_comments_and_quoted_braces_do_not_change_context(files):
    site, snippet = files
    source = SITE.replace("    listen 443 ssl;", '''    listen 443 ssl;
    add_header X-Test "brace } and #quoted";
    # location ^~ /mini-app/api/ { proxy_pass http://invalid;
    # location /uploads/ { return 403; }
''')
    site.write_text(source)
    installer.configure(site, snippet, run=lambda args: None)
    assert site.read_text().replace(f'    include "{snippet.as_posix()}";\n', "", 1) == source


def test_commented_api_does_not_qualify(files):
    site, snippet = files
    source = SITE.replace("    location ^~ /mini-app/api/", "    # location ^~ /mini-app/api/")
    site.write_text(source)
    with pytest.raises(ValueError):
        installer.configure(site, snippet, run=lambda args: pytest.fail("No reload"))
    assert site.read_text() == source
    assert not snippet.exists()

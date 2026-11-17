"""Release smoke must respect an intentionally isolated VK vhost."""

import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/verify_vk_miniapp_mode.sh"
SHA = "a" * 40


@pytest.mark.parametrize(
    ("revision_status", "index_status", "revision_body", "expected"),
    [
        (410, 410, "", "disabled"),
        (200, 200, SHA, "enabled"),
        (410, 200, "", None),
        (200, 200, "b" * 40, None),
        (502, 502, "", None),
    ],
)
def test_vk_smoke_mode(revision_status, index_status, revision_body, expected):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            is_revision = self.path.startswith("/revision.txt")
            status = revision_status if is_revision else index_status
            body = (revision_body if is_revision else "index").encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = subprocess.run(
            [
                "bash", str(HELPER),
                f"http://127.0.0.1:{server.server_address[1]}", SHA,
            ],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    if expected is None:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected


def test_telegram_smoke_stays_strict_and_vk_build_is_skipped_when_isolated():
    deploy = (ROOT / "scripts/deploy_miniapp_local.sh").read_text()
    workflow = (ROOT / ".github/workflows/deploy-production-reliable.yml").read_text()
    assert 'if [[ "$VK_ISOLATED" == 0 ]]; then' in deploy
    assert 'if [[ "$vk_mode" == enabled && "$VK_ISOLATED" == 0 ]]; then' in deploy
    assert 'VK_DISABLED' in deploy
    assert '[[ "$live_revision" == "$EXPECTED_SHA" ]]' in deploy
    # The VK helper is tested independently, but production must not probe retired VK DNS.
    assert 'vk_mode="$(bash scripts/verify_vk_miniapp_mode.sh https://vk.neuromixbot.com' not in workflow
    assert 'https://vk.neuromixbot.com' not in workflow
    assert '[ "$live_frontend_revision" = "$EXPECTED_SHA" ]' in workflow

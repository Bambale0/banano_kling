"""Public regression contract for NEUROMIX root landing, separate from Mini App."""
import unittest
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "web/landing"


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.headings = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "a":
            self.links.append(data.get("href", ""))
        if tag == "h1":
            self.headings.append(data)
        if "id" in data:
            self.ids.add(data["id"])


class LandingPublicContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (LANDING / "index.html").read_text(encoding="utf-8")
        cls.nginx = (ROOT / "ops/nginx/neuromixbot.com.conf").read_text(encoding="utf-8")
        cls.deploy = (ROOT / "scripts/deploy_miniapp_local.sh").read_text(encoding="utf-8")
        cls.publisher = (ROOT / "scripts/deploy_landing_local.sh").read_text(encoding="utf-8")
        cls.page = Parser()
        cls.page.feed(cls.html)

    def test_semantics_and_mobile_viewport(self):
        self.assertEqual(1, len(self.page.headings))
        self.assertIn('<html lang="ru">', self.html)
        self.assertIn("width=device-width,initial-scale=1", self.html)
        self.assertIn("prefers-reduced-motion:reduce", self.html)
        self.assertIn("safe-area-inset-bottom", self.html)

    def test_real_app_entrypoints_and_honest_future_auth(self):
        self.assertGreaterEqual(self.page.links.count("/mini-app/"), 3)
        self.assertEqual(set(self.page.links) - {"/mini-app/", "/"}, {"#possibilities", "#login"})
        for method in ("Telegram", "Почта", "Google", "Яндекс ID", "скоро"):
            self.assertIn(method, self.html)
        self.assertNotIn('href="/oauth/google', self.html)
        self.assertNotIn('href="/oauth/yandex', self.html)
        for link in self.page.links:
            if link.startswith("#"):
                self.assertIn(link[1:], self.page.ids)

    def test_legacy_telegram_webview_launch_bypasses_public_landing(self):
        self.assertIn("tgWebAppData", self.html)
        self.assertIn("tgWebAppVersion", self.html)
        self.assertIn("tgWebAppStartParam", self.html)
        self.assertIn("'startapp'", self.html)
        self.assertIn("window.location.replace('/mini-app/'", self.html)
        self.assertIn("window.location.hash", self.html)

    def test_uses_existing_miniapp_color_tokens(self):
        theme = (ROOT / "frontend/miniapp-v0/app/globals.css").read_text(encoding="utf-8")
        for key, value in (
            ("--background", "oklch(0.12 0.015 260)"),
            ("--primary", "oklch(0.78 0.14 75)"),
            ("--accent", "oklch(0.65 0.12 220)"),
        ):
            self.assertIn(key + ": " + value, theme)
            self.assertIn(key + ": " + value, self.html)

    def test_redesign_is_short_real_entry_portal_not_fake_app(self):
        # Marketing root remains a small no-dependency gateway, not a second app.
        self.assertIn('class="container hero-grid"', self.html)
        self.assertIn('class="container access-layout"', self.html)
        self.assertIn('id="login-title"', self.html)
        self.assertIn("Идея —", self.html)
        self.assertNotIn('<script src=', self.html)
        self.assertNotIn("99.9%", self.html)
        self.assertNotIn('href="/login/email', self.html)
        self.assertNotIn('href="/login/google', self.html)
        self.assertNotIn('href="/login/yandex', self.html)
        self.assertLess(len(self.html.encode("utf-8")), 40000)

    def test_mobile_sticky_action_waits_until_primary_button_is_out_of_view(self):
        self.assertIn("IntersectionObserver", self.html)
        self.assertIn("observer.observe(heroButton)", self.html)
        self.assertIn("dock.classList.toggle('is-visible'", self.html)
        self.assertIn(".mobile-dock.is-visible", self.html)
        self.assertIn("pointer-events:none", self.html)
        self.assertIn('aria-hidden="true" inert', self.html)
        self.assertIn("dock.toggleAttribute('inert', !visible)", self.html)

    def test_mobile_and_accessibility_seams(self):
        self.assertIn("@media (max-width:760px)", self.html)
        self.assertIn("@media (max-width:380px)", self.html)
        self.assertIn(".mobile-dock", self.html)
        self.assertIn("a:focus-visible", self.html)
        self.assertIn("prefers-reduced-motion:reduce", self.html)
        self.assertIn('aria-label="Основная навигация"', self.html)
        self.assertIn('class="telegram-entry"', self.html)

    def test_seo_metadata(self):
        self.assertIn('href="https://neuromixbot.com/"', self.html)
        self.assertIn('name="description"', self.html)
        self.assertIn('property="og:title"', self.html)

    def test_nginx_root_and_app_routing(self):
        self.assertIn("location = / {\n        root /var/www/neuromix-landing;\n        try_files /index.html =404;", self.nginx)
        self.assertNotIn("return 302 /mini-app/;", self.nginx)
        self.assertIn("location ^~ /mini-app/api/", self.nginx)
        self.assertIn("location /mini-app/", self.nginx)
        self.assertIn("location = /robots.txt", self.nginx)
        self.assertIn("location = /sitemap.xml", self.nginx)

    def test_release_runs_after_miniapp_smoke_and_has_rollback(self):
        self.assertLess(self.deploy.index('log "LIVE_OK '), self.deploy.index("deploy_landing_local.sh"))
        for fragment in ("git -C", "nginx -t", "systemctl reload nginx", "rollback", "miniapp_revision"):
            self.assertIn(fragment, self.publisher)

    def test_publisher_waits_for_real_200_after_async_nginx_reload(self):
        self.assertIn("for mode in origin public; do", self.publisher)
        self.assertIn("attempt<=30", self.publisher)
        self.assertIn('[[ "$status" == 200 ]]', self.publisher)
        self.assertIn('grep -q \'id="hero-title"\'', self.publisher)

    def test_landing_isolated_from_shared_miniapp_document_root(self):
        self.assertIn('root /var/www/neuromix-landing;', self.nginx)
        self.assertIn('ROOT="/var/www/neuromix-landing"', self.publisher)
        self.assertIn('[[ ! -L "$ROOT" ]]', self.publisher)
        self.assertIn('install -d -m 0755 "$ROOT"', self.publisher)
        self.assertNotIn('ROOT="/var/www/$HOST"', self.publisher)

    def test_public_sitemap(self):
        robots = (LANDING / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap: https://neuromixbot.com/sitemap.xml", robots)
        tree = ElementTree.parse(LANDING / "sitemap.xml")
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        self.assertEqual("https://neuromixbot.com/", tree.findtext("s:url/s:loc", namespaces=ns))


if __name__ == "__main__":
    unittest.main()

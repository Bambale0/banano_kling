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
        self.assertEqual(set(self.page.links) - {"/mini-app/", "/"}, {"#possibilities", "#how", "#login"})
        for method in ("Telegram", "Почта", "Google", "Яндекс ID", "скоро"):
            self.assertIn(method, self.html)
        self.assertNotIn('href="/oauth/google', self.html)
        self.assertNotIn('href="/oauth/yandex', self.html)
        for link in self.page.links:
            if link.startswith("#"):
                self.assertIn(link[1:], self.page.ids)

    def test_uses_existing_miniapp_color_tokens(self):
        theme = (ROOT / "frontend/miniapp-v0/app/globals.css").read_text(encoding="utf-8")
        for key, value in (
            ("--background", "oklch(0.12 0.015 260)"),
            ("--primary", "oklch(0.78 0.14 75)"),
            ("--accent", "oklch(0.65 0.12 220)"),
        ):
            self.assertIn(key + ": " + value, theme)
            self.assertIn(key + ": " + value, self.html)

    def test_seo_metadata(self):
        self.assertIn('href="https://neuromixbot.com/"', self.html)
        self.assertIn('name="description"', self.html)
        self.assertIn('property="og:title"', self.html)

    def test_nginx_root_and_app_routing(self):
        self.assertIn("location = / {\n        try_files /index.html =404;", self.nginx)
        self.assertNotIn("return 302 /mini-app/;", self.nginx)
        self.assertIn("location ^~ /mini-app/api/", self.nginx)
        self.assertIn("location /mini-app/", self.nginx)
        self.assertIn("location = /robots.txt", self.nginx)
        self.assertIn("location = /sitemap.xml", self.nginx)

    def test_release_runs_after_miniapp_smoke_and_has_rollback(self):
        self.assertLess(self.deploy.index('log "LIVE_OK '), self.deploy.index("deploy_landing_local.sh"))
        for fragment in ("git -C", "nginx -t", "systemctl reload nginx", "rollback", "miniapp_revision"):
            self.assertIn(fragment, self.publisher)

    def test_public_sitemap(self):
        robots = (LANDING / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("Sitemap: https://neuromixbot.com/sitemap.xml", robots)
        tree = ElementTree.parse(LANDING / "sitemap.xml")
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        self.assertEqual("https://neuromixbot.com/", tree.findtext("s:url/s:loc", namespaces=ns))


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(set(self.page.links) - {"/mini-app/", "/"}, {"#possibilities", "#benefits", "#how", "#examples", "/login"})
        for method in ("Telegram", "Почта", "Google", "Яндекс ID", "скоро"):
            self.assertIn(method, self.html)
        self.assertNotIn('href="/oauth/google', self.html)
        self.assertNotIn('href="/oauth/yandex', self.html)
        for link in self.page.links:
            if link.startswith("#"):
                self.assertIn(link[1:], self.page.ids)

    def test_login_is_real_shadcn_route_not_a_fake_oauth_button(self):
        page = (ROOT / "frontend/miniapp-v0/app/login/page.tsx").read_text(encoding="utf-8")
        panel = (ROOT / "frontend/miniapp-v0/components/landing-login-panel.tsx").read_text(encoding="utf-8")
        css = (ROOT / "frontend/miniapp-v0/app/login/login.css").read_text(encoding="utf-8")
        self.assertIn('href="/login"', self.html)
        self.assertEqual(self.page.links.count("/login"), 3)
        self.assertIn("LoginPanel", page)
        for component in ("Button", "Card", "Badge", "Separator"):
            self.assertIn(component, panel)
        self.assertIn("/mini-app/api/browser-auth/config", panel)
        self.assertIn("/mini-app/api/browser-auth", panel)
        self.assertIn("telegram_auth: user", panel)
        self.assertIn("tgWebAppData", panel)
        self.assertIn("window.location.replace(studioUrlWithSession", panel)
        self.assertIn("skoro", panel.replace("скоро", "skoro"))
        self.assertIn("neuromix-login", css)
        self.assertNotIn('href="/oauth/google', panel)
        self.assertNotIn("localStorage.setItem", panel)

    def test_login_nginx_routing_and_safe_release_smoke(self):
        self.assertIn("location = /login {", self.nginx)
        self.assertIn("location = /login/ {", self.nginx)
        self.assertIn("try_files /mini-app/login/index.html =404;", self.nginx)
        self.assertIn('OUT_DIR}/login/index.html', self.deploy)
        self.assertIn("login_block", self.publisher)
        self.assertIn("for path in /login /login/; do", self.publisher)
        self.assertIn('id="login-page-title"', self.publisher)
        self.assertIn("location ^~ /mini-app/api/", self.nginx)
        self.assertIn("location /mini-app/", self.nginx)

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
        self.assertIn('class="grunge-desktop"', self.html)
        self.assertIn('class="grunge-mobile"', self.html)
        self.assertIn('class="container access-layout"', self.html)
        self.assertIn('id="login-title"', self.html)
        self.assertIn("Превращай идеи", self.html)
        self.assertNotIn('<script src=', self.html)
        self.assertNotIn("99.9%", self.html)
        self.assertNotIn('href="/login/email', self.html)
        self.assertNotIn('href="/login/google', self.html)
        self.assertNotIn('href="/login/yandex', self.html)
        self.assertLess(len(self.html.encode("utf-8")), 50000)

    def test_mobile_sticky_action_waits_until_primary_button_is_out_of_view(self):
        self.assertIn("IntersectionObserver", self.html)
        self.assertIn("observer.observe(heroButton)", self.html)
        self.assertIn("document.querySelector('.mobile-grunge-cta')", self.html)
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


    def test_eight_marketing_sections_and_factual_content(self):
        ids = ("hero-title", "problems", "benefits", "how", "examples", "pricing", "faq", "login")
        for section_id in ids:
            self.assertIn(f'id="{section_id}"', self.html)
        self.assertIn("Фото, видео и тренды", self.html)
        self.assertIn("Актуальные пакеты пополнения", self.html)
        self.assertIn("не выдуманные отзывы", self.html)
        self.assertNotIn("₽ за генерацию", self.html)
        self.assertNotIn("бесплатных генераций", self.html)
        self.assertEqual(4, self.html.count('class="story-row"'))
        self.assertEqual(4, self.html.count('class="step-number"'))
        self.assertEqual(5, self.html.count("<details>"))
        self.assertEqual(5, self.html.count("<summary>"))
        self.assertIn('id="login-title"', self.html)
        self.assertIn('href="/mini-app/"', self.html)

    def test_faq_is_native_accessible_and_trust_does_not_fabricate_testimonials(self):
        self.assertIn('<section class="section-faq" id="faq"', self.html)
        self.assertIn("Сейчас веб-версия использует вход через Telegram", self.html)
        self.assertIn("картинка будущего", self.html)
        self.assertIn("Здесь показаны реальные разделы продукта", self.html)
        self.assertNotIn('class="fake-review"', self.html)
        self.assertIn(".faq-items summary:focus-visible", self.html)

    def test_grunge_hero_uses_approved_art_with_real_clickable_regions(self):
        self.assertIn('grunge-hero-v1.webp', self.html)
        self.assertIn('grunge-mobile-art-v1.webp', self.html)
        self.assertIn('class="grunge-poster"', self.html)
        self.assertIn('class="hotspot hot-hero-cta"', self.html)
        self.assertIn('class="hotspot hot-enter"', self.html)
        self.assertIn('class="mobile-grunge-cta"', self.html)
        self.assertIn('class="screenreader-only"', self.html)
        self.assertIn('class="grunge-mobile-title"', self.html)
        self.assertIn('id="hero-title"', self.html)
        self.assertIn('aria-label="Основная навигация"', self.html)
        self.assertIn('background:#090b0c url("grunge-hero-v1.webp")', self.html)
        for name in ("grunge-hero-v1.webp", "grunge-mobile-art-v1.webp"):
            asset = LANDING / name
            self.assertTrue(asset.is_file(), name)
            data = asset.read_bytes()
            self.assertGreater(len(data), 100_000)
            self.assertTrue(data.startswith(b"RIFF") and data[8:12] == b"WEBP")
            self.assertIn(f'location = /{name} {{', self.nginx)
            self.assertIn(f'/{name}', self.publisher)
        self.assertIn("image/webp", self.publisher)

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
        self.assertIn("location = /grunge-hero-v1.webp", self.nginx)
        self.assertIn("location = /grunge-mobile-art-v1.webp", self.nginx)

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

from pathlib import Path


MINIAPP_INDEX_PATH = Path(__file__).resolve().parents[1] / "static" / "miniapp" / "index.html"


def test_miniapp_shell_uses_flowchart_content_design():
    html = MINIAPP_INDEX_PATH.read_text(encoding="utf-8")

    assert "2LOOP MINI APP" in html
    assert "telegram-web-app.js" in html
    assert "2LOOP AI CONTENT FLOW" in html
    assert "OUTPUT MENU" in html
    assert "3 BRANCHES" in html
    assert "GOE BALANCE" in html
    assert "data-action=\"create\"" in html
    assert "/api/miniapp/products" in html

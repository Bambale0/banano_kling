"""Private, in-memory Astro PDF; no URLs, attachments or arbitrary metadata."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from textwrap import wrap
from threading import Event, Lock
from time import monotonic
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

PDF_FILENAME = "astro_neuromix.pdf"
# Conservative multipart upload bound, below Telegram's 50 MB Bot API limit.
MAX_PDF_BYTES = 49_000_000
MAX_TEXT_BYTES = 3_000_000  # Matches the existing encrypted report envelope.
MAX_PDF_PAGES = 2000
MAX_LAYOUT_BLOCKS = 25_000
SERVICE_NAMES = {
    "natal": "Натальная карта",
    "compatibility": "Совместимость",
    "karma": "Кармический разбор",
    "year": "Прогноз на год",
    "month": "Прогноз на месяц",
    "solar": "Соляр",
    "lunar": "Лунный календарь",
}
_FONT_LOCK = Lock()


def _register_fonts() -> None:
    with _FONT_LOCK:
        if "AstroNoto" not in pdfmetrics.getRegisteredFontNames():
            fonts = Path(__file__).resolve().parents[1] / "assets" / "fonts"
            pdfmetrics.registerFont(TTFont("AstroNoto", str(fonts / "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("AstroNotoBold", str(fonts / "NotoSans-Bold.ttf")))


def render_astro_pdf(report: dict, *, cancel_event: Event | None = None,
                     deadline: float | None = None) -> bytes:
    """Render all completed sections without truncation or a text fallback.

    Only the decrypted owner-scoped report is supplied, never inputs or
    credentials. Escaping prevents model text from creating links, images,
    local-file reads, PDF actions or external requests.
    """
    def check_budget() -> None:
        if (cancel_event is not None and cancel_event.is_set()) or (
                deadline is not None and monotonic() >= deadline):
            raise TimeoutError("Astro PDF rendering deadline reached")

    check_budget()
    if not isinstance(report, dict) or report.get("status") != "completed":
        raise ValueError("Astro PDF requires a completed report")
    service = report.get("service_id")
    if not isinstance(service, str) or service not in SERVICE_NAMES:
        raise ValueError("Unsupported Astro report service")
    sections = report.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("Astro PDF has no sections")
    content = []
    text_bytes = 0
    for section in sections:
        check_budget()
        if not isinstance(section, dict):
            raise TypeError("Invalid Astro PDF section")
        title, body = section.get("title", "Раздел"), section.get("text")
        if not isinstance(title, str) or not isinstance(body, str) or not body.strip():
            raise ValueError("Invalid Astro PDF section text")
        text_bytes += len(title.encode("utf-8")) + len(body.encode("utf-8"))
        content.append((title, body))
    disclaimer = report.get("disclaimer", "")
    if not isinstance(disclaimer, str):
        raise TypeError("Invalid Astro PDF disclaimer")
    text_bytes += len(disclaimer.encode("utf-8"))
    if text_bytes > MAX_TEXT_BYTES:
        raise ValueError("Astro PDF input exceeds encrypted report limit")

    _register_fonts()
    check_budget()
    body_style = ParagraphStyle(
        "AstroBody", fontName="AstroNoto", fontSize=10.5, leading=16,
        spaceAfter=9, splitLongWords=True, allowWidows=0, allowOrphans=0,
    )
    title_style = ParagraphStyle(
        "AstroTitle", parent=body_style, fontName="AstroNotoBold",
        fontSize=22, leading=29, spaceAfter=20,
    )
    section_style = ParagraphStyle(
        "AstroSection", parent=body_style, fontName="AstroNotoBold",
        fontSize=15, leading=21, spaceBefore=15, spaceAfter=10,
    )
    note_style = ParagraphStyle(
        "AstroNote", parent=body_style, fontSize=9, leading=13,
        textColor=colors.HexColor("#525866"), spaceBefore=16,
    )
    story = [Paragraph("Astro / NEUROMIX", note_style),
             Paragraph(escape(SERVICE_NAMES[service]), title_style)]

    def add_text(text: str, style: ParagraphStyle) -> None:
        # Bound layout cost for a 30k-word single paragraph; headings can split.
        for chunk in wrap(text, width=2000, replace_whitespace=False,
                          drop_whitespace=False, break_long_words=True,
                          break_on_hyphens=False):
            check_budget()
            if len(story) >= MAX_LAYOUT_BLOCKS:
                raise ValueError("Astro PDF layout budget exceeded")
            story.append(Paragraph(escape(chunk).replace("\n", "<br/>"), style))

    for title, body in content:
        add_text(title, section_style)
        for paragraph in body.split("\n\n"):
            if paragraph.strip():
                add_text(paragraph, body_style)
    if disclaimer:
        add_text(disclaimer, note_style)

    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=48, rightMargin=48,
        topMargin=48, bottomMargin=48, pageCompression=1,
        title="Astro / NEUROMIX", author="NEUROMIX", subject="Astro",
    )

    def footer(canvas, doc):
        check_budget()
        if doc.page > MAX_PDF_PAGES:
            raise ValueError("Astro PDF page budget exceeded")
        canvas.saveState()
        canvas.setFont("AstroNoto", 8)
        canvas.setFillColor(colors.HexColor("#697080"))
        canvas.drawString(48, 27, "Astro / NEUROMIX")
        canvas.drawRightString(A4[0] - 48, 27, f"Страница {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    data = output.getvalue()
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("Astro PDF exceeds Telegram upload limit")
    return data

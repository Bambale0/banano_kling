"""Read real exported PDFs through an independent parser, using synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event, Lock
from time import monotonic

import pytest
from pypdf import PdfReader

from bot.services import astro_report_pdf
from bot.services.astro_report_pdf import render_astro_pdf


def report(text="Съешь ещё этих мягких французских булок. Ёжик и южный узел."):
    return {"status": "completed", "service_id": "natal", "sections": [
        {"title": "Введение", "text": text},
        {"title": "Заключение", "text": "Последний раздел не потерян."},
    ], "disclaimer": "Символическая интерпретация."}


def read(data):
    assert data.startswith(b"%PDF-") and len(data) > 10_000
    reader = PdfReader(BytesIO(data), strict=True)
    return reader, "\n".join(page.extract_text() for page in reader.pages)


def test_cyrillic_and_all_sections_are_searchable_with_embedded_fonts():
    reader, text = read(render_astro_pdf(report()))
    for expected in ["Съешь ещё", "Ёжик и южный узел.", "Введение", "Заключение",
                     "Последний раздел не потерян.", "Символическая интерпретация."]:
        assert expected in text
    fonts = reader.pages[0]["/Resources"]["/Font"]
    embedded = [font.get_object().get("/FontDescriptor") for font in fonts.values()]
    assert any(item and "/FontFile2" in item for item in embedded)
    assert "Страница 1" in text


def test_astronomical_symbols_and_emoji_use_embedded_glyph_fonts():
    reader, text = read(render_astro_pdf(report('Солнце ☉ Луна ☽ Овен ♈ Рыбы ♓ Венера ♀ Марс ♂ → ✨ ⚠ 😀')))
    assert 'Солнце ☉ Луна ☽ Овен ♈ Рыбы ♓ Венера ♀ Марс ♂ → ✨ ⚠ 😀' in text
    fonts = reader.pages[0]['/Resources']['/Font']
    names = str([font.get_object().get('/BaseFont') for font in fonts.values()])
    assert 'NotoSansSymbols-Regular' in names
    assert 'NotoSansSymbols2-Regular' in names
    assert 'NotoEmoji' in names


def test_concurrent_exports_keep_unicode_maps_and_text_separate():
    fixtures = [report('Первый ☉ ♈ 😀'), report('Второй ☽ ♓ ✨')]
    with ThreadPoolExecutor(max_workers=2) as executor:
        documents = list(executor.map(render_astro_pdf, fixtures))
    _, first = read(documents[0])
    _, second = read(documents[1])
    assert 'Первый ☉ ♈ 😀' in first and 'Второй' not in first
    assert 'Второй ☽ ♓ ✨' in second and 'Первый' not in second


@pytest.fixture
def held_pdf_build(monkeypatch):
    """Hold one real library build while observing other public exports."""
    document_type = astro_report_pdf.SimpleDocTemplate
    original_build = document_type.build
    guard = Lock()
    state = {"active": 0, "peak": 0, "calls": 0, "documents": 0,
             "entered": Event(), "second_entered": Event(),
             "second_prepared": Event(), "release": Event()}

    def create_document(*args, **kwargs):
        document = document_type(*args, **kwargs)
        with guard:
            state["documents"] += 1
            if state["documents"] == 2:
                state["second_prepared"].set()
        return document

    def build(document, *args, **kwargs):
        with guard:
            state["calls"] += 1
            call = state["calls"]
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            if call == 1:
                state["entered"].set()
                assert state["release"].wait(3), "test did not release first build"
            else:
                state["second_entered"].set()
            return original_build(document, *args, **kwargs)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(document_type, "build", build)
    monkeypatch.setattr(astro_report_pdf, "SimpleDocTemplate", create_document)
    yield state
    state["release"].set()


def test_shared_font_builds_never_overlap(held_pdf_build):
    state = held_pdf_build
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(render_astro_pdf, report("Первый ☉ ♈ 😀"))
        try:
            assert state["entered"].wait(2)
            second = executor.submit(render_astro_pdf, report("Второй ☽ ♓ ✨"))
            assert state["second_prepared"].wait(2)
            overlapped = state["second_entered"].wait(0.15)
        finally:
            state["release"].set()
        documents = [first.result(timeout=3), second.result(timeout=3)]
    assert not overlapped and state["peak"] == 1
    texts = [read(data)[1] for data in documents]
    assert "Первый ☉ ♈ 😀" in texts[0] and "Второй" not in texts[0]
    assert "Второй ☽ ♓ ✨" in texts[1] and "Первый" not in texts[1]


@pytest.mark.parametrize("budget", ["cancel", "deadline"])
def test_waiting_export_exits_without_entering_build(held_pdf_build, budget, monkeypatch):
    state = held_pdf_build
    cancel = Event()
    clock = [0.0]
    monkeypatch.setattr(astro_report_pdf, "monotonic", lambda: clock[0])
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(render_astro_pdf, report())
        try:
            assert state["entered"].wait(2)
            options = {"cancel_event": cancel} if budget == "cancel" else {"deadline": 1.0}
            waiter = executor.submit(render_astro_pdf, report("Ожидающий документ"), **options)
            assert state["second_prepared"].wait(2)
            if budget == "cancel":
                cancel.set()
            else:
                clock[0] = 2.0
            with pytest.raises(TimeoutError, match="Astro PDF rendering deadline"):
                waiter.result(timeout=0.8)
            assert state["calls"] == 1
        finally:
            state["release"].set()
        read(first.result(timeout=3))
    # A cancelled waiter must neither start later nor leak the build lock.
    read(render_astro_pdf(report("Следующий документ")))
    assert state["calls"] == 2


def test_build_exception_releases_shared_font_guard(monkeypatch):
    original_build = astro_report_pdf.SimpleDocTemplate.build

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic layout failure")

    monkeypatch.setattr(astro_report_pdf.SimpleDocTemplate, "build", fail)
    with pytest.raises(RuntimeError, match="synthetic layout"):
        render_astro_pdf(report())
    monkeypatch.setattr(astro_report_pdf.SimpleDocTemplate, "build", original_build)
    read(render_astro_pdf(report("После ошибки"), deadline=monotonic() + 2))


def test_unsupported_glyph_fails_closed_instead_of_delivering_empty_boxes():
    with pytest.raises(ValueError, match='unsupported glyph'):
        render_astro_pdf(report('\u9fff'))


@pytest.mark.parametrize("word_count", [10_000, 30_000])
def test_long_single_section_spans_pages_without_losing_words(word_count):
    fixture = report("началораздела " + "кириллица " * word_count + "конецраздела")
    reader, text = read(render_astro_pdf(fixture))
    assert len(reader.pages) > 10
    assert text.count("кириллица") == word_count
    assert "началораздела" in text and "конецраздела" in text
    assert "Последний раздел не потерян." in text
    assert all(page.extract_text().strip() for page in reader.pages)
    assert f"Страница {len(reader.pages)}" in text


@pytest.mark.parametrize("service", ["natal", "compatibility", "karma", "year", "month", "solar", "lunar"])
def test_every_service_exports_all_dynamic_sections(service):
    fixture = report()
    fixture["service_id"] = service
    fixture["sections"] += [{"title": f"День {day}", "text": f"Разделпериода{day}"}
                            for day in range(1, 32)]
    _, text = read(render_astro_pdf(fixture))
    for day in range(1, 32):
        assert f"Разделпериода{day}" in text


def test_export_excludes_private_metadata_and_escapes_active_material():
    fixture = report('<img src="file:///DO_NOT_READ"/> <a href="https://invalid.test">Текст</a> & данные')
    fixture.update({"owner_id": "SYNTHETIC_OWNER_PRIVATE", "facts": {"name": "SYNTHETIC_PII"},
                    "ClientID": "SYNTHETIC_CLIENT_ID", "client_secret": "SYNTHETIC_SECRET",
                    "attachments": ["file:///DO_NOT_READ"]})
    fixture["sections"][0]["private"] = "SYNTHETIC_SECTION_PRIVATE"
    reader, text = read(render_astro_pdf(fixture))
    assert '<img src="file:///DO_NOT_READ"/>' in text
    assert "& данные" in text
    assert "SYNTHETIC_" not in text + str(reader.metadata)
    assert all(not page.get("/Annots") for page in reader.pages)
    assert not reader.trailer["/Root"].get("/OpenAction")
    assert not reader.trailer["/Root"].get("/Names")


@pytest.mark.parametrize("invalid", [{}, {"status": "running"},
    {"status": "completed", "service_id": "natal", "sections": []},
    {"status": "completed", "service_id": "natal", "sections": [{"text": ""}]},
    {"status": "completed", "service_id": "natal", "sections": [{"text": None}]},
    {"status": "completed", "service_id": "unknown", "sections": [{"text": "x"}]}])
def test_invalid_report_never_becomes_an_empty_or_partial_pdf(invalid):
    with pytest.raises(ValueError):
        render_astro_pdf(invalid)


def test_limits_fail_closed_without_truncation(monkeypatch):
    with pytest.raises(ValueError, match="encrypted report limit"):
        render_astro_pdf(report("Я" * 1_500_001))
    monkeypatch.setattr(astro_report_pdf, "MAX_PDF_BYTES", 10_000)
    with pytest.raises(ValueError, match="Telegram upload limit"):
        render_astro_pdf(report())


def test_renderer_honors_cancel_and_deadline():
    cancelled = Event()
    cancelled.set()
    with pytest.raises(TimeoutError, match="deadline"):
        render_astro_pdf(report(), cancel_event=cancelled)
    with pytest.raises(TimeoutError, match="deadline"):
        render_astro_pdf(report(), deadline=monotonic()-1)


def test_pathological_layout_is_bounded_without_partial_pdf(monkeypatch):
    monkeypatch.setattr(astro_report_pdf, "MAX_PDF_PAGES", 1)
    with pytest.raises(ValueError, match="page budget"):
        render_astro_pdf(report("Строка отчёта.\n" * 1000))
    monkeypatch.setattr(astro_report_pdf, "MAX_LAYOUT_BLOCKS", 3)
    with pytest.raises(ValueError, match="layout budget"):
        render_astro_pdf(report("Абзац\n\n" * 1000))

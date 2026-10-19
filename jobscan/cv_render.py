"""Render helper shared by the CV and the cover letter."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cv"))
import render as _r  # noqa: E402


def _set_metadata(pdf: Path, name: str, title: str, subject: str) -> None:
    """Give the PDF proper document metadata.

    Headless Chrome stamps /Creator = "...HeadlessChrome/152..." and
    /Producer = "Skia/PDF", which tells a reader nothing useful and looks
    like a machine artefact on a document meant to be from a person. The
    master CV carries Author/Title/Subject/Keywords and nothing else; these
    match it.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("  ! pypdf missing - PDF metadata not set", file=__import__("sys").stderr)
        return
    try:
        reader = PdfReader(str(pdf))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.add_metadata({
            "/Author": name,
            "/Title": title,
            "/Subject": subject,
            "/Creator": name,
            "/Producer": name,
        })
        tmp = pdf.with_suffix(".tmp.pdf")
        with open(tmp, "wb") as fh:
            writer.write(fh)
        tmp.replace(pdf)
    except Exception as exc:  # noqa: BLE001 - cosmetic, must never fail a render
        print(f"  ! could not set PDF metadata: {type(exc).__name__}",
              file=__import__("sys").stderr)


def render_cv(data: dict, out_pdf: Path) -> tuple[int, int]:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html = _r.render_html(data, "template.html")
    _r.html_to_pdf(html, out_pdf)
    result = _r.verify(out_pdf)
    name = data.get("name", "")
    _set_metadata(out_pdf, name, f"{name} - Curriculum Vitae", "Curriculum Vitae")
    return result


def render_letter(data: dict, out_pdf: Path) -> tuple[int, int]:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html = _r.render_html(data, "letter.html")
    _r.html_to_pdf(html, out_pdf)
    # A letter is much shorter than a CV, so the CV threshold would reject it.
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(out_pdf))
    text = "".join(p.get_textpage().get_text_range() for p in doc)
    n = len(text.strip())
    if n < 800:
        raise RuntimeError(
            f"TEXT LAYER MISSING: only {n} extractable chars. Do not send it.")
    pages = len(doc)
    doc.close()
    name = data.get("name", "")
    emp = (data.get("letter") or {}).get("employer", "")
    _set_metadata(out_pdf, name, f"{name} - Cover Letter",
                  f"Cover letter{' - ' + emp if emp else ''}")
    return (pages, n)

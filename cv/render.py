"""Render a CV from master.json + template.html into a text-layer PDF.

The model never touches layout. It may only ever produce the JSON content;
this renderer owns presentation, so generated CVs cannot drift in formatting.

Printing goes through headless Chrome because it embeds real fonts and emits
a proper text layer. The previous CV was exported via macOS Quartz, which
outlined the glyphs and produced a PDF that ATS parsers read as empty.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from jobscan.hostenv import chrome as _find_chrome
except Exception:  # noqa: BLE001 - render.py is also runnable standalone
    _find_chrome = lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME = _find_chrome()
MIN_CHARS = 600  # a missing text layer yields ~0; even a short CV has well over this


def render_html(data: dict, template: str = "template.html") -> str:
    env = Environment(
        loader=FileSystemLoader(HERE),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template(template).render(**data)


def html_to_pdf(html: str, out_pdf: Path) -> None:
    if not CHROME or not Path(CHROME).exists():
        raise RuntimeError(
            "No Chrome or Chromium found. Install one: "
            "macOS 'brew install --cask google-chrome', "
            "Ubuntu 'sudo apt install chromium-browser'.")
    tmp = Path(tempfile.mkdtemp(prefix="cvrender-"))
    try:
        src = tmp / "cv.html"
        src.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                CHROME, "--headless=new", "--disable-gpu",
                "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={tmp/'profile'}",
                "--virtual-time-budget=20000",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_pdf}",
                src.as_uri(),
            ],
            capture_output=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        pass  # Chrome sometimes writes the PDF then fails to exit
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not out_pdf.exists():
        raise RuntimeError("Chrome produced no PDF")


def verify(pdf: Path) -> tuple[int, int]:
    """Return (pages, extractable chars). Raises if the text layer is missing."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("  ! pypdfium2 not installed - skipping text-layer check", file=sys.stderr)
        return (0, -1)
    doc = pdfium.PdfDocument(str(pdf))
    text = "".join(p.get_textpage().get_text_range() for p in doc)
    n = len(text.strip())
    if n < MIN_CHARS:
        raise RuntimeError(
            f"TEXT LAYER MISSING: only {n} extractable chars. "
            "An ATS would read this as blank. Do not send it."
        )
    return (len(doc), n)


def main() -> None:
    data_path = HERE / (sys.argv[1] if len(sys.argv) > 1 else "master.json")
    out_pdf = HERE / (sys.argv[2] if len(sys.argv) > 2 else "out/master.pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    data = json.loads(data_path.read_text())
    html = render_html(data)
    (out_pdf.with_suffix(".html")).write_text(html, encoding="utf-8")
    html_to_pdf(html, out_pdf)
    pages, chars = verify(out_pdf)
    print(f"OK  {out_pdf}  pages={pages}  extractable_chars={chars}")


if __name__ == "__main__":
    main()

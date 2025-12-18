from __future__ import annotations
import re
from pathlib import Path

from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


SECTION_LINE = re.compile(
    r"^(?:[A-Z]-\d{3,4}\s*[,\-]?\s+.+|B-\d{3}\s+.+|Part\s+[A-Z],\s+.+|Section\s+\d{3,4},\s+.+)$",
    re.IGNORECASE,
)

JUNK_EXACT = {
    "search this handbook",
    "printer-friendly version",
    "twh glossary",
    "twh forms",
    "twh notices",
    "twh revisions",
    "twh policy bulletins",
    "twh contact us",
}

JUNK_SUBSTRINGS = [
    "menu button for",
    "skip to main content",
    "breadcrumb",
]


def _is_junk_line(line: str) -> bool:
    s = line.strip().lower()
    if not s:
        return True
    if s in JUNK_EXACT:
        return True
    return any(sub in s for sub in JUNK_SUBSTRINGS)


def _looks_like_toc(lines: list[str]) -> bool:
    if not lines:
        return True

    short_sectionish = 0
    long_para = 0

    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        if len(t) >= 140:
            long_para += 1
        if len(t) <= 90 and SECTION_LINE.match(t):
            short_sectionish += 1

    return short_sectionish >= 10 and long_para <= 2


def _extract_main_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.select_one("#main-content")
        or soup.select_one(".region-content")
    )

    return main if main is not None else soup


def parse_html_to_text(html_path: str | Path) -> str:
    html_path = Path(html_path)
    html = html_path.read_text(encoding="utf-8", errors="ignore")

    root = _extract_main_soup(html)

    raw_lines: list[str] = []

    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li"], recursive=True):
        text = el.get_text(" ", strip=True)
        if not text:
            continue

        # Drop TOC-style list items: short, section-like, link-heavy
        if el.name == "li":
            has_link = el.find("a") is not None
            starts_like_section = bool(SECTION_LINE.match(text))
            if has_link and starts_like_section and len(text) <= 90:
                continue

        raw_lines.append(text)

    cleaned: list[str] = []
    prev = None
    for ln in raw_lines:
        ln = ln.strip()
        if _is_junk_line(ln):
            continue
        if prev and ln == prev:
            continue
        cleaned.append(ln)
        prev = ln

    # Skip table-of-contents dumps
    if _looks_like_toc(cleaned):
        return ""

    out_lines: list[str] = []
    for ln in cleaned:
        if SECTION_LINE.match(ln) or ln.isupper():
            out_lines.extend(["", ln, ""])  # spacing around headers
        else:
            out_lines.append(ln)

    out = "\n".join([l for l in out_lines if l is not None])
    out = "\n".join([l.rstrip() for l in out.splitlines()])
    out = "\n".join([l for l in out.splitlines() if l.strip()])
    return out


def parse_pdf_to_text(pdf_path: str | Path) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf not installed. Add 'pypdf' to requirements.txt")

    pdf_path = Path(pdf_path)
    reader = PdfReader(str(pdf_path))

    parts: list[str] = []
    for page in reader.pages:
        txt = (page.extract_text() or "").strip()
        if txt:
            parts.append(txt)

    return "\n\n".join(parts)


def clean_all(raw_dir: str | Path = "data/raw", processed_dir: str | Path = "data/processed") -> None:
    raw_dir = Path(raw_dir)
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    skipped = 0

    # Process all HTML (including subfolders if any)
    for hp in sorted(raw_dir.rglob("*.html")):
        # Skip anything inside the pdfs directory
        if "pdfs" in hp.parts:
            continue

        text = parse_html_to_text(hp)
        if not text:
            skipped += 1
            print(f"SKIP (TOC/no-content): {hp.name}")
            continue

        out_path = processed_dir / f"{hp.stem}.txt"
        out_path.write_text(text, encoding="utf-8")
        saved += 1
        print(f"Saved text: {out_path}")

    # Process PDFs
    pdf_dir = raw_dir / "pdfs"
    if pdf_dir.exists():
        for pp in sorted(pdf_dir.glob("*.pdf")):
            try:
                pdf_text = parse_pdf_to_text(pp)
                if not pdf_text.strip():
                    print(f"SKIP (no extractable text): {pp.name}")
                    continue
                out_path = processed_dir / f"{pp.stem}.txt"
                out_path.write_text(pdf_text, encoding="utf-8")
                print(f"Saved PDF text: {out_path}")
            except Exception as e:
                print(f"FAILED PDF: {pp.name} | {e}")

    print("\nPages cleaning summary")
    print(f"  html_saved: {saved}")
    print(f"  html_skipped: {skipped}")


if __name__ == "__main__":
    clean_all()

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, HttpUrl

from src.core.logging import get_logger

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import fitz  # pymupdf
except Exception:
    fitz = None

logger = get_logger("ingest.pages")


# Heuristic: lines that look like handbook sections / headings
SECTION_LINE = re.compile(
    r"^(?:"
    r"[A-Z]-\d{3,4}\s*[,\-]?\s+.+|"
    r"B-\d{3}\s+.+|"
    r"Part\s+[A-Z],\s+.+|"
    r"Section\s+\d{3,4},\s+.+"
    r")$",
    re.IGNORECASE,
)

# Common nav/footer junk text seen on government handbook pages
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
    "skip to main content",
    "menu button",
    "breadcrumb",
]


class FetchRecord(BaseModel):
    run_id: str
    doc_id: str
    url: HttpUrl
    kind: Literal["html", "pdf"]
    content_type: str = ""
    bytes: int = Field(ge=0)
    saved_path: str
    fetched_at: str


class OrganizedDoc(BaseModel):
    doc_id: str
    url: HttpUrl
    kind: Literal["html", "pdf"]
    source_path: str
    processed_path: str
    text_chars: int = Field(ge=0)
    created_at: str


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _is_junk_line(line: str) -> bool:
    s = line.strip().lower()
    if not s:
        return True
    if s in JUNK_EXACT:
        return True
    return any(sub in s for sub in JUNK_SUBSTRINGS)


def _looks_like_toc(lines: list[str]) -> bool:
    """Detect table-of-contents pages that are mostly short section-like lines."""
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

    # Lots of section-looking lines, few long paragraphs => likely TOC
    return short_sectionish >= 10 and long_para <= 2


def _extract_main_root(html: str) -> BeautifulSoup:
    """Remove obvious non-content elements and choose a best-effort main content root."""
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
    """Convert a raw HTML file into cleaned plain text suitable for chunking."""
    html_path = Path(html_path)
    html = html_path.read_text(encoding="utf-8", errors="ignore")

    root = _extract_main_root(html)

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

    # De-dupe and remove junk
    cleaned: list[str] = []
    prev: Optional[str] = None
    for ln in raw_lines:
        ln = ln.strip()
        if _is_junk_line(ln):
            continue
        if prev and ln == prev:
            continue
        cleaned.append(ln)
        prev = ln

    # Skip TOC-like pages
    if _looks_like_toc(cleaned):
        return ""

    # Improve readability: add blank lines around headings
    out_lines: list[str] = []
    for ln in cleaned:
        if SECTION_LINE.match(ln) or ln.isupper():
            out_lines.extend(["", ln, ""])  # spacing around headers
        else:
            out_lines.append(ln)

    # Normalize whitespace
    out = "\n".join(out_lines)
    out = "\n".join([l.rstrip() for l in out.splitlines()])

    # Collapse multiple blank lines
    collapsed: list[str] = []
    blank_run = 0
    for line in out.splitlines():
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                collapsed.append("")
            continue
        blank_run = 0
        collapsed.append(line)

    # Trim leading/trailing blanks
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()

    return "\n".join(collapsed)


def parse_pdf_to_text(pdf_path: str | Path) -> str:
    """Extract text from PDF using pypdf first, then pymupdf fallback."""
    pdf_path = Path(pdf_path)

    if PdfReader is not None:
        try:
            reader = PdfReader(str(pdf_path))
            parts: list[str] = []
            for page in reader.pages:
                txt = (page.extract_text() or "").strip()
                if txt:
                    parts.append(txt)
            joined = "\n\n".join(parts).strip()
            if joined:
                return joined
        except Exception:
            pass

    if fitz is None:
        raise RuntimeError("No PDF extractor available. Install 'pypdf' or 'pymupdf'.")

    doc = fitz.open(str(pdf_path))
    parts: list[str] = []
    for page in doc:
        txt = (page.get_text("text") or "").strip()
        if txt:
            parts.append(txt)
    doc.close()
    return "\n\n".join(parts).strip()


def _load_manifest_map(raw_dir: Path) -> Dict[str, FetchRecord]:
    """Map doc_id -> FetchRecord from data/raw/fetch_manifest.jsonl."""
    manifest_path = raw_dir / "fetch_manifest.jsonl"
    rows = _read_jsonl(manifest_path)

    out: Dict[str, FetchRecord] = {}
    for r in rows:
        try:
            rec = FetchRecord.model_validate(r)
            out[rec.doc_id] = rec
        except Exception as e:
            logger.warning(f"manifest_row_invalid error={e} row_keys={list(r.keys())}")

    return out


def _infer_url_from_doc_id(doc_id: str) -> str | None:
    """Best-effort URL reconstruction for legacy/uncrawled docs without a manifest record.

    Many stored raw filenames follow: "<domain>_<path with underscores>.html".
    Example:
      doc_id="www.hhs.texas.gov_services_food_snap-food-benefits"
      -> https://www.hhs.texas.gov/services/food/snap-food-benefits
    """

    s = doc_id.strip()
    if not s:
        return None
    if s.startswith(("http://", "https://")):
        return s

    if "_" not in s:
        return None

    domain, rest = s.split("_", 1)
    if "." not in domain:
        return None

    path = rest.replace("_", "/").lstrip("/")
    return f"https://{domain}/{path}" if path else f"https://{domain}"


def _fallback_url(doc_id: str) -> str:
    # Keep OrganizedDoc validation happy when old raw files have no manifest row.
    return _infer_url_from_doc_id(doc_id) or f"https://example.com/unknown/{doc_id}"


def _make_organized_doc(
    *,
    doc_id: str,
    kind: Literal["html", "pdf"],
    source_path: Path,
    processed_path: Path,
    text_chars: int,
    created_at: str,
    rec: FetchRecord | None,
) -> OrganizedDoc:
    return OrganizedDoc(
        doc_id=doc_id,
        url=rec.url if rec is not None else _fallback_url(doc_id),
        kind=kind,
        source_path=str(source_path),
        processed_path=str(processed_path),
        text_chars=text_chars,
        created_at=created_at,
    )


def organize_all(
    raw_dir: str | Path = "data/raw",
    processed_dir: str | Path = "data/processed",
    organized_dir: str | Path = "data/organized",
) -> dict[str, int]:
    """Convert raw HTML/PDF into cleaned .txt files + write docs index.

    Outputs:
      - data/processed/<doc_id>.txt
      - data/organized/docs.jsonl

    Returns counters for monitoring.
    """

    raw_dir = Path(raw_dir)
    processed_dir = Path(processed_dir)
    organized_dir = Path(organized_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    organized_dir.mkdir(parents=True, exist_ok=True)

    manifest_map = _load_manifest_map(raw_dir)

    html_saved = 0
    html_skipped = 0
    pdf_saved = 0
    pdf_skipped = 0
    pdf_failed = 0

    organized_rows: list[dict] = []
    created_at = _utc_iso()

    # HTML
    for hp in sorted(raw_dir.rglob("*.html")):
        if "pdfs" in hp.parts:
            continue

        doc_id = hp.stem
        rec = manifest_map.get(doc_id)
        if rec is None:
            logger.warning(f"missing_manifest_for_html doc_id={doc_id} path={hp}")

        text = parse_html_to_text(hp)
        if not text:
            html_skipped += 1
            logger.info(f"skip_html_empty doc_id={doc_id} path={hp.name}")
            continue

        out_path = processed_dir / f"{doc_id}.txt"
        out_path.write_text(text, encoding="utf-8")
        html_saved += 1

        meta = _make_organized_doc(
            doc_id=doc_id,
            kind="html",
            source_path=hp,
            processed_path=out_path,
            text_chars=len(text),
            created_at=created_at,
            rec=rec,
        )
        organized_rows.append(meta.model_dump(mode="json"))

        logger.info(f"saved_html doc_id={doc_id} chars={len(text)} out={out_path}")

    # PDFs
    pdf_dir = raw_dir / "pdfs"
    if pdf_dir.exists():
        for pp in sorted(pdf_dir.glob("*.pdf")):
            doc_id = pp.stem
            rec = manifest_map.get(doc_id)
            if rec is None:
                logger.warning(f"missing_manifest_for_pdf doc_id={doc_id} path={pp}")

            try:
                pdf_text = parse_pdf_to_text(pp)
                if not pdf_text.strip():
                    pdf_skipped += 1
                    logger.info(f"skip_pdf_empty doc_id={doc_id} path={pp.name}")
                    continue

                out_path = processed_dir / f"{doc_id}.txt"
                out_path.write_text(pdf_text, encoding="utf-8")
                pdf_saved += 1

                meta = _make_organized_doc(
                    doc_id=doc_id,
                    kind="pdf",
                    source_path=pp,
                    processed_path=out_path,
                    text_chars=len(pdf_text),
                    created_at=created_at,
                    rec=rec,
                )
                organized_rows.append(meta.model_dump(mode="json"))

                logger.info(f"saved_pdf doc_id={doc_id} chars={len(pdf_text)} out={out_path}")

            except Exception as e:
                pdf_failed += 1
                logger.exception(f"failed_pdf doc_id={doc_id} path={pp.name} error={e}")

    index_path = organized_dir / "docs.jsonl"
    _write_jsonl(index_path, organized_rows)

    logger.info(
        f"stage=organize_summary html_saved={html_saved} html_skipped={html_skipped} "
        f"pdf_saved={pdf_saved} pdf_skipped={pdf_skipped} pdf_failed={pdf_failed} index={index_path}"
    )

    return {
        "html_saved": html_saved,
        "html_skipped": html_skipped,
        "pdf_saved": pdf_saved,
        "pdf_skipped": pdf_skipped,
        "pdf_failed": pdf_failed,
    }


# Backwards-compatible alias
clean_all = organize_all

__all__ = ["organize_all", "clean_all", "parse_html_to_text", "parse_pdf_to_text"]


if __name__ == "__main__":
    summary = organize_all()
    logger.info(f"summary={summary}")

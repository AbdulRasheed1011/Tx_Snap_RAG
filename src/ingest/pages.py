from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup


def parse_html_to_text(html_path: str | Path) -> str:
    """Parse a single HTML file into cleaned, readable text.

    - Removes common boilerplate tags (script/style/nav/header/footer).
    - Preserves headings by uppercasing them and surrounding with blank lines.
    """

    html_path = Path(html_path)

    with html_path.open("r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy/irrelevant blocks
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    lines: list[str] = []

    # Extract useful content in document order
    for element in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        text = element.get_text(" ", strip=True)
        if not text:
            continue

        if element.name in ["h1", "h2", "h3"]:
            lines.append(f"\n{text.upper()}\n")
        else:
            lines.append(text)

    # Join and lightly normalize whitespace
    clean_text = "\n".join(lines)
    clean_text = "\n".join([ln.strip() for ln in clean_text.splitlines() if ln.strip()])

    return clean_text


def clean_raw_html_dir(
    raw_dir: str | Path = "data/raw",
    processed_dir: str | Path = "data/processed",
    glob_pattern: str = "*.html",
) -> dict:
    """Clean all HTML files from raw_dir and save text outputs into processed_dir.

    - Input:  data/raw/*.html
    - Output: data/processed/<same_name>.txt

    Returns a small summary dict for logging/prints.
    """

    raw_dir = Path(raw_dir)
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")

    html_files: Iterable[Path] = sorted(raw_dir.glob(glob_pattern))

    saved = 0
    failed: list[dict] = []

    for html_path in html_files:
        try:
            text = parse_html_to_text(html_path)

            out_name = html_path.stem + ".txt"
            out_path = processed_dir / out_name

            out_path.write_text(text, encoding="utf-8")
            saved += 1
            print(f"Cleaned: {html_path.name} -> {out_path}")

        except Exception as e:
            failed.append({"file": str(html_path), "error": str(e)})
            print(f"FAILED: {html_path} | {e}")

    summary = {
        "raw_dir": str(raw_dir),
        "processed_dir": str(processed_dir),
        "pattern": glob_pattern,
        "total": len(list(raw_dir.glob(glob_pattern))),
        "saved": saved,
        "failed": failed,
    }

    return summary


if __name__ == "__main__":
    # Run from project root:
    #   python -m src.ingest.pages
    summary = clean_raw_html_dir()
    print("\nSummary:")
    print(f"  total: {summary['total']}")
    print(f"  saved: {summary['saved']}")
    print(f"  failed: {len(summary['failed'])}")

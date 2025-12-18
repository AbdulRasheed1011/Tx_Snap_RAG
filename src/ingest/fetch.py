from __future__ import annotations
import json
import os
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

from src.utils.config import load_config


def norm_url(url: str) -> str:
    url = (url or "").strip()
    url, _ = urldefrag(url)
    return url

def norm_host(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")

def safe_filename(url: str, ext: str) -> str:
    p = urlparse(url)
    base = f"{p.netloc}{p.path}"
    if not base or base.endswith("/"):
        base += "index"
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", base)
    if not base.lower().endswith(ext):
        base += ext
    return base[:200]
class Fetcher:
    def __init__(
        self,
        seed_urls: list[str],
        allowed_domains: list[str],
        allowed_patterns: list[str] | None = None,
        deny_patterns: list[str] | None = None,
        crawl_depth: int = 1,
        max_pages: int = 200,
        timeout_seconds: int = 15,
        user_agent: str = "tx-snap-rag-bot/1.0",
        max_pdfs_per_page: int = 10,
        raw_dir: str | Path = "data/raw",
    ):
        self.seed_urls = [norm_url(u) for u in (seed_urls or []) if norm_url(u)]
        self.allowed_domains = [str(d).lower().replace("www.", "") for d in (allowed_domains or [])]
        self.allowed_patterns = allowed_patterns or []
        self.deny_patterns = deny_patterns or []

        self.crawl_depth = int(crawl_depth)
        self.max_pages = int(max_pages)
        self.timeout_seconds = int(timeout_seconds)
        self.user_agent = str(user_agent)
        self.max_pdfs_per_page = int(max_pdfs_per_page)

        self.raw_dir = Path(raw_dir)
        self.pdf_dir = self.raw_dir / "pdfs"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

        self.manifest_path = self.raw_dir / "manifest.jsonl"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
            }
        )

    def is_allowed_domain(self, url: str) -> bool:
        host = norm_host(url)
        if not host:
            return False
        for ad in self.allowed_domains:
            if host == ad or host.endswith("." + ad):
                return True
        return False

    def is_denied(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(p.lower() in path for p in self.deny_patterns)

    def matches_allowed_patterns(self, url: str) -> bool:
        # If no allow patterns, allow everything inside allowed_domains.
        if not self.allowed_patterns:
            return True
        path = urlparse(url).path
        return any(pat in path for pat in self.allowed_patterns)

    def is_pdf_url(self, url: str) -> bool:
        return urlparse(url).path.lower().endswith(".pdf")

    def should_visit(self, url: str) -> bool:
        url = norm_url(url)
        if not url:
            return False
        if not self.is_allowed_domain(url):
            return False
        if self.is_denied(url):
            return False

        
        if self.is_pdf_url(url):
            return True

    
        return self.matches_allowed_patterns(url)

    def log(self, record: dict) -> None:
        with self.manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def fetch(self, url: str):
        return self.session.get(url, timeout=self.timeout_seconds)

    def extract_links(self, base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            if not href:
                continue
            abs_url = norm_url(urljoin(base_url, href))
            if abs_url:
                links.append(abs_url)
        return links

    def run(self) -> None:

        if self.manifest_path.exists():
            self.manifest_path.unlink()

        q = deque()
        seen: set[str] = set()

        for u in self.seed_urls:
            q.append((u, 0, None))  # (url, depth, parent)

        saved_count = 0

        while q and saved_count < self.max_pages:
            url, depth, parent = q.popleft()
            url = norm_url(url)

            if not url or url in seen:
                continue
            seen.add(url)

            if not self.should_visit(url):
                self.log(
                    {
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "url": url,
                        "depth": depth,
                        "parent": parent,
                        "status": "skipped",
                        "reason": "blocked_by_rules",
                    }
                )
                continue

            try:
                resp = self.fetch(url)
                resp.raise_for_status()

                content_type = (resp.headers.get("Content-Type") or "").lower()
                is_pdf = ("application/pdf" in content_type) or self.is_pdf_url(url)

                if is_pdf:
                    out_path = self.pdf_dir / safe_filename(url, ".pdf")
                    out_path.write_bytes(resp.content)
                    saved_count += 1
                    print(f"Saved PDF: {out_path}")

                    self.log(
                        {
                            "ts": datetime.utcnow().isoformat() + "Z",
                            "url": url,
                            "depth": depth,
                            "parent": parent,
                            "status": "saved",
                            "type": "pdf",
                            "content_type": content_type,
                            "path": str(out_path),
                            "bytes": len(resp.content),
                        }
                    )
                    continue

                # HTML
                html = resp.text
                out_path = self.raw_dir / safe_filename(url, ".html")
                out_path.write_text(html, encoding="utf-8")
                saved_count += 1
                print(f"Saved HTML: {out_path}")

                self.log(
                    {
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "url": url,
                        "depth": depth,
                        "parent": parent,
                        "status": "saved",
                        "type": "html",
                        "content_type": content_type,
                        "path": str(out_path),
                        "bytes": len(html.encode("utf-8", errors="ignore")),
                    }
                )

                # Crawl deeper
                if depth < self.crawl_depth:
                    links = self.extract_links(url, html)

                    pdf_links: list[str] = []
                    html_links: list[str] = []

                    for link in links:
                        link = norm_url(link)
                        if not link:
                            continue
                        if not self.is_allowed_domain(link) or self.is_denied(link):
                            continue

                        if self.is_pdf_url(link):
                            pdf_links.append(link)
                        else:
                            # Only enqueue HTML if it matches allowed_patterns
                            if self.matches_allowed_patterns(link):
                                html_links.append(link)

                    # de-dup + limit
                    pdf_links = list(dict.fromkeys(pdf_links))[: self.max_pdfs_per_page]
                    html_links = list(dict.fromkeys(html_links))

                    if pdf_links:
                        print(f"  Found {len(pdf_links)} PDF link(s)")

                    for link in pdf_links:
                        if link not in seen:
                            q.append((link, depth + 1, url))

                    for link in html_links:
                        if link not in seen:
                            q.append((link, depth + 1, url))

            except Exception as e:
                print(f"FAILED: {url} | {e}")
                self.log(
                    {
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "url": url,
                        "depth": depth,
                        "parent": parent,
                        "status": "error",
                        "error": str(e),
                    }
                )

        print("\nFetch complete")
        print(f"  saved_count: {saved_count}")
        print(f"  seen_total: {len(seen)}")
        print(f"  manifest: {self.manifest_path}")


def fetch_from_config(config_path: str = "config.yaml") -> None:
    cfg = load_config(config_path)
    sources = cfg.get("sources", {})
    ingestion = cfg.get("ingestion", {})

    fetcher = Fetcher(
        seed_urls=sources.get("seed_urls", []),
        allowed_domains=sources.get("allowed_domains", []),
        allowed_patterns=sources.get("allowed_patterns", []),
        deny_patterns=sources.get("deny_patterns", []),
        crawl_depth=ingestion.get("crawl_depth", 1),
        max_pages=ingestion.get("max_pages", 200),
        timeout_seconds=ingestion.get("timeout_seconds", 15),
        user_agent=ingestion.get("user_agent", "tx-snap-rag-bot/1.0"),
        max_pdfs_per_page=ingestion.get("max_pdfs_per_page", 10),
        raw_dir="data/raw",
    )

    fetcher.run()


if __name__ == "__main__":
    fetch_from_config("config.yaml")
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Literal

import requests
from pydantic import BaseModel, Field, HttpUrl

from src.core.logging import get_logger
from src.core.context import get_run_id
from src.core.settings import AppConfig

logger = get_logger("ingest.fetch")


class FetchRecord(BaseModel):
    run_id: str
    doc_id: str
    url: HttpUrl
    kind: Literal["html", "pdf"]
    content_type: str = ""
    bytes: int = Field(ge=0)
    saved_path: str
    fetched_at: str  # ISO 8601


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _is_pdf(url: str, content_type: Optional[str]) -> bool:
    ct = (content_type or "").lower()
    return url.lower().endswith(".pdf") or "application/pdf" in ct


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def fetch_seed_urls(cfg: AppConfig, out_raw_dir="data/raw", *, overwrite=False, run_id: str | None = None):
    run_id = run_id or get_run_id()

    out_raw_dir = Path(out_raw_dir)
    out_pdf_dir = out_raw_dir / "pdfs"
    out_raw_dir.mkdir(parents=True, exist_ok=True)
    out_pdf_dir.mkdir(parents=True, exist_ok=True)

    timeout = int(cfg.ingestion.timeout_seconds)
    headers = {"User-Agent": cfg.ingestion.user_agent}

    ok = 0
    skipped = 0
    failed = 0
    manifest_rows: list[dict] = []

    seed_urls = [str(u) for u in cfg.sources.seed_urls]
    logger.info(
        f"run_id={run_id} stage=fetch_start seed_urls={len(seed_urls)} out_dir={out_raw_dir} overwrite={overwrite}"
    )

    for url in seed_urls:
        doc_id = _stable_id(url)
        html_path = out_raw_dir / f"{doc_id}.html"
        pdf_path = out_pdf_dir / f"{doc_id}.pdf"

        # Idempotency: skip if already present unless overwrite=True
        if not overwrite and (html_path.exists() or pdf_path.exists()):
            skipped += 1
            logger.info(f"run_id={run_id} skip_exists url={url} doc_id={doc_id}")
            continue

        try:
            logger.info(f"run_id={run_id} fetching url={url}")
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            fetched_at = _utc_iso()

            if _is_pdf(url, content_type):
                pdf_path.write_bytes(resp.content)
                rec = FetchRecord(
                    run_id=run_id,
                    doc_id=doc_id,
                    url=url,
                    kind="pdf",
                    content_type=content_type,
                    bytes=len(resp.content),
                    saved_path=str(pdf_path),
                    fetched_at=fetched_at,
                )
                manifest_rows.append(rec.model_dump())
                ok += 1
                logger.info(f"run_id={run_id} saved kind=pdf path={pdf_path} bytes={len(resp.content)}")
                continue

            html_path.write_text(resp.text, encoding="utf-8", errors="ignore")
            rec = FetchRecord(
                run_id=run_id,
                doc_id=doc_id,
                url=url,
                kind="html",
                content_type=content_type,
                bytes=len(resp.content),
                saved_path=str(html_path),
                fetched_at=fetched_at,
            )
            manifest_rows.append(rec.model_dump())
            ok += 1
            logger.info(f"run_id={run_id} saved kind=html path={html_path} bytes={len(resp.content)}")

        except requests.HTTPError as e:
            failed += 1
            status = getattr(e.response, "status_code", None)
            logger.exception(f"run_id={run_id} failed url={url} status={status} error={e}")
        except requests.RequestException as e:
            failed += 1
            logger.exception(f"run_id={run_id} failed url={url} error={e}")
        except Exception as e:
            failed += 1
            logger.exception(f"run_id={run_id} failed url={url} error={e}")

    manifest_path = out_raw_dir / "fetch_manifest.jsonl"
    _write_jsonl(manifest_path, manifest_rows)

    logger.info(
        f"run_id={run_id} stage=fetch_done ok={ok} skipped={skipped} failed={failed} manifest={manifest_path}"
    )
    return {"ok": ok, "skipped": skipped, "failed": failed}
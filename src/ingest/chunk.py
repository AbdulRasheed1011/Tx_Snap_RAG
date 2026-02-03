from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from pydantic import BaseModel, Field, HttpUrl

from src.core.logging import get_logger

logger = get_logger("ingest.chunk")

# Bump this if you ever want to sanity-check you're importing the expected file.
CHUNK_MODULE_VERSION = "v1"


# ---------
# Models
# ---------

class OrganizedDoc(BaseModel):
    doc_id: str
    url: HttpUrl
    kind: str
    source_path: str
    processed_path: str
    text_chars: int = Field(ge=0)
    created_at: str


class ChunkRecord(BaseModel):
    doc_id: str
    chunk_id: str
    url: HttpUrl
    kind: str
    text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    token_estimate: int = Field(ge=0)
    created_at: str


# ---------
# Utils
# ---------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+\n?|\n+")


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


def _stable_chunk_id(doc_id: str, start: int, end: int) -> str:
    raw = f"{doc_id}:{start}:{end}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _token_estimate(text: str) -> int:
    """Fast token approximation. Uses tiktoken if available; otherwise ~4 chars/token heuristic."""
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # crude but stable for monitoring
        return max(1, (len(text) + 3) // 4)


def _normalize_text(text: str) -> str:
    # collapse excessive whitespace but keep paragraph breaks
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------
# Chunking method
# ---------

def chunk_text(
    text: str,
    *,
    max_chars: int = 1800,
    overlap_chars: int = 200,
    min_chunk_chars: int = 200,
) -> List[tuple[str, int, int]]:
    """Structure-aware chunking (paragraph/sentence first) with overlap.

    Method:
      1) Normalize text.
      2) Build chunks by adding paragraphs until max_chars.
      3) If a paragraph is too large, split it by sentences.
      4) Always add overlap between adjacent chunks.

    Returns list of (chunk_text, start_char, end_char) offsets in the normalized text.
    """

    text = _normalize_text(text)
    if not text:
        return []

    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[tuple[str, int, int]] = []

    cursor = 0

    def find_next_span(snippet: str, start_at: int) -> tuple[int, int]:
        idx = text.find(snippet, start_at)
        if idx == -1:
            # Fallback: best-effort; do not crash the pipeline
            return start_at, min(len(text), start_at + len(snippet))
        return idx, idx + len(snippet)

    buffer_parts: List[str] = []

    def flush_buffer() -> None:
        nonlocal cursor
        if not buffer_parts:
            return
        chunk = "\n\n".join(buffer_parts).strip()

        if len(chunk) < min_chunk_chars and chunks:
            prev_text, prev_s, _prev_e = chunks[-1]
            merged = (prev_text + "\n\n" + chunk).strip()
            chunks[-1] = (merged, prev_s, prev_s + len(merged))
            buffer_parts.clear()
            return

        s, e = find_next_span(chunk, cursor)
        chunks.append((chunk, s, e))
        cursor = e
        buffer_parts.clear()

    for p in paras:
        if len(p) > max_chars:
            flush_buffer()

            sents = [s.strip() for s in _SENT_SPLIT.split(p) if s.strip()]
            tmp: List[str] = []
            for s in sents:
                if sum(len(x) + 1 for x in tmp) + len(s) <= max_chars:
                    tmp.append(s)
                else:
                    big = " ".join(tmp).strip()
                    if big:
                        ss, ee = find_next_span(big, cursor)
                        chunks.append((big, ss, ee))
                        cursor = ee
                    tmp = [s]

            tail = " ".join(tmp).strip()
            if tail:
                ss, ee = find_next_span(tail, cursor)
                chunks.append((tail, ss, ee))
                cursor = ee
            continue

        proposed = ("\n\n".join(buffer_parts + [p])).strip()
        if len(proposed) <= max_chars:
            buffer_parts.append(p)
        else:
            flush_buffer()
            buffer_parts.append(p)

    flush_buffer()

    # Add overlap between adjacent chunks
    if overlap_chars > 0 and len(chunks) > 1:
        overlapped: List[tuple[str, int, int]] = []
        for i, (ct, s, e) in enumerate(chunks):
            if i == 0:
                overlapped.append((ct, s, e))
                continue
            prev_text, _prev_s, _prev_e = overlapped[-1]

            overlap = prev_text[-overlap_chars:] if len(prev_text) > overlap_chars else prev_text
            merged = (overlap + "\n" + ct).strip()
            overlapped.append((merged, s, e))

        chunks = overlapped

    return chunks


# ---------
# Pipeline stage
# ---------

def chunk_all(
    *,
    organized_index: str | Path = "data/organized/docs.jsonl",
    processed_dir: str | Path = "data/processed",
    out_dir: str | Path = "data/chunks",
    max_chars: int = 1800,
    overlap_chars: int = 200,
    min_chunk_chars: int = 200,
) -> dict[str, int]:
    """Read organized docs index + processed text, write chunks JSONL."""

    organized_index = Path(organized_index)
    processed_dir = Path(processed_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    docs: List[OrganizedDoc] = []
    for r in _read_jsonl(organized_index):
        try:
            docs.append(OrganizedDoc.model_validate(r))
        except Exception as e:
            logger.warning(f"organized_row_invalid error={e} keys={list(r.keys())}")

    logger.info(
        f"stage=chunk_start docs={len(docs)} max_chars={max_chars} overlap_chars={overlap_chars} min_chunk_chars={min_chunk_chars}"
    )

    created_at = _utc_iso()
    chunk_rows: List[dict] = []

    docs_ok = 0
    docs_missing = 0
    chunks_written = 0

    for d in docs:
        text_path = Path(d.processed_path)
        if not text_path.is_absolute():
            text_path = (Path.cwd() / text_path).resolve()

        if not text_path.exists():
            text_path = processed_dir / f"{d.doc_id}.txt"

        if not text_path.exists():
            docs_missing += 1
            logger.warning(f"missing_processed doc_id={d.doc_id} expected={d.processed_path}")
            continue

        text = text_path.read_text(encoding="utf-8", errors="ignore")
        pieces = chunk_text(
            text,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            min_chunk_chars=min_chunk_chars,
        )

        if not pieces:
            logger.info(f"skip_doc_empty doc_id={d.doc_id} path={text_path.name}")
            continue

        for ct, s, e in pieces:
            rec = ChunkRecord(
                doc_id=d.doc_id,
                chunk_id=_stable_chunk_id(d.doc_id, s, e),
                url=d.url,
                kind=d.kind,
                text=ct,
                start_char=s,
                end_char=e,
                token_estimate=_token_estimate(ct),
                created_at=created_at,
            )
            chunk_rows.append(rec.model_dump(mode="json"))
            chunks_written += 1

        docs_ok += 1
        logger.info(f"chunked_doc doc_id={d.doc_id} chunks={len(pieces)}")

    out_path = out_dir / "chunks.jsonl"
    _write_jsonl(out_path, chunk_rows)

    logger.info(
        f"stage=chunk_done docs_ok={docs_ok} docs_missing={docs_missing} chunks={chunks_written} out={out_path}"
    )

    return {"docs_ok": docs_ok, "docs_missing": docs_missing, "chunks": chunks_written}


__all__ = ["CHUNK_MODULE_VERSION", "chunk_all", "chunk_text", "ChunkRecord", "OrganizedDoc"]


if __name__ == "__main__":
    summary = chunk_all()
    logger.info(f"summary={summary}")
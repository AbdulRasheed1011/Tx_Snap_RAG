from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import faiss
import numpy as np
from openai import OpenAI
from tqdm import tqdm

from src.core.settings import AppConfig


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    metadata: Dict[str, Any]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {line_no} in {path}: {e}") from e


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms


def _batched(items: List[str], batch_size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def load_chunks(chunks_path: Path, *, min_text_chars: int = 20) -> List[Chunk]:
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    out: List[Chunk] = []
    for row in _read_jsonl(chunks_path):
        text = str(row.get("text", "")).strip()
        if len(text) < min_text_chars:
            continue

        chunk_id = str(row.get("chunk_id") or "").strip()
        if not chunk_id:
            continue

        doc_id = str(row.get("doc_id") or "unknown_doc")
        start_char = _to_int(row.get("start_char"), 0)
        end_char = _to_int(row.get("end_char"), 0)

        metadata = {
            "doc_id": doc_id,
            "url": str(row.get("url") or ""),
            "kind": str(row.get("kind") or ""),
            "start_char": start_char,
            "end_char": end_char,
            "token_estimate": _to_int(row.get("token_estimate"), 0),
            "created_at": str(row.get("created_at") or ""),
            # Compatibility fields for tools that still display source/section.
            "source_file": doc_id,
            "section": f"{start_char}-{end_char}",
        }
        out.append(Chunk(chunk_id=chunk_id, text=text, metadata=metadata))

    if not out:
        raise RuntimeError(f"No usable chunks found in {chunks_path}")

    return out


def embed_openai(
    *,
    client: OpenAI,
    texts: List[str],
    model: str,
    batch_size: int,
) -> np.ndarray:
    vectors: List[List[float]] = []
    total_batches = (len(texts) + batch_size - 1) // batch_size

    for batch in tqdm(_batched(texts, batch_size), total=total_batches, desc="Embedding"):
        response = client.embeddings.create(model=model, input=batch)
        batch_vectors = [item.embedding for item in response.data]
        if len(batch_vectors) != len(batch):
            raise RuntimeError(
                f"Embedding count mismatch: got {len(batch_vectors)} vectors for {len(batch)} texts."
            )
        vectors.extend(batch_vectors)

    return np.asarray(vectors, dtype=np.float32)


def main() -> None:
    cfg = AppConfig.load("config.yaml")
    if cfg.embedding.provider != "openai":
        raise ValueError(f"Unsupported embedding provider: {cfg.embedding.provider}")

    chunks_path = Path("data/chunks/chunks.jsonl")
    out_dir = Path("artifacts/index")
    out_dir.mkdir(parents=True, exist_ok=True)

    index_path = out_dir / "index.faiss"
    meta_path = out_dir / "meta.jsonl"
    run_meta_path = out_dir / "index_meta.json"

    print(f"[load] chunks from: {chunks_path}")
    chunks = load_chunks(chunks_path)
    print(f"[load] usable chunks: {len(chunks)}")

    texts = [c.text for c in chunks]

    print(f"[embed] provider=openai model={cfg.embedding.model} batch_size={cfg.embedding.batch_size}")
    client = OpenAI()
    vectors = embed_openai(
        client=client,
        texts=texts,
        model=cfg.embedding.model,
        batch_size=cfg.embedding.batch_size,
    )
    vectors = _l2_normalize(vectors)

    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)
    faiss.write_index(index, str(index_path))

    meta_rows: List[Dict[str, Any]] = []
    for row, chunk in enumerate(chunks):
        meta_rows.append(
            {
                "row": row,
                "id": chunk.chunk_id,
                "metadata": chunk.metadata,
                "text": chunk.text,
            }
        )
    _write_jsonl(meta_path, meta_rows)

    run_meta = {
        "created_at": _utc_iso(),
        "embedding_provider": cfg.embedding.provider,
        "embedding_model": cfg.embedding.model,
        "vectors": len(chunks),
        "dimension": dim,
        "chunks_path": str(chunks_path),
        "index_path": str(index_path),
        "meta_path": str(meta_path),
    }
    run_meta_path.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[save] index: {index_path}")
    print(f"[save] meta: {meta_path}")
    print(f"[save] run meta: {run_meta_path}")
    print("[done] FAISS index build complete.")


if __name__ == "__main__":
    main()

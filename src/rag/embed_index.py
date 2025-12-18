from __future__ import annotations

import os
import json
import glob
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

import numpy as np
from tqdm import tqdm
import tensorflow_hub as hub
import faiss


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: Dict[str, Any]


def read_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    """
    Reads JSONL. Also tolerates a file that contains a single JSON object on one line.
    """
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {line_no} in {path}: {e}") from e


def make_chunk_id(source_file: str, section: str, text: str) -> str:
    # Stable + deterministic. If text changes, id changes. Good.
    h = hashlib.sha1()
    h.update(source_file.encode("utf-8"))
    h.update(b"|")
    h.update(section.encode("utf-8"))
    h.update(b"|")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def load_chunks_from_folder(folder: str) -> List[Chunk]:
    paths = sorted(glob.glob(os.path.join(folder, "*.chunks.jsonl")))
    if not paths:
        raise RuntimeError(f"No *.chunks.jsonl files found in: {folder}")

    out: List[Chunk] = []
    for p in paths:
        for obj in read_jsonl(p):
            text = str(obj.get("text", "")).strip()
            if not text or len(text) < 20:
                continue

            source_file = str(obj.get("source_file") or os.path.basename(p)).strip()
            section = str(obj.get("section") or "UNKNOWN").strip()

            cid = make_chunk_id(source_file, section, text)
            meta = {
                "source_file": source_file,
                "section": section,
                "chunk_file": os.path.basename(p),
            }

            out.append(Chunk(id=cid, text=text, metadata=meta))

    if not out:
        raise RuntimeError("Loaded 0 usable chunks. Your chunk texts might be empty/too short.")
    return out


def batched(items: List[str], batch_size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def main() -> None:
    # --- Inputs ---
    chunks_dir = "data/organize"  # <- matches your repo
    # --- Outputs ---
    out_dir = "artifacts/index"
    index_path = os.path.join(out_dir, "index.faiss")
    meta_path = os.path.join(out_dir, "meta.jsonl")

    # --- Embedding model (TensorFlow-only) ---
    # Universal Sentence Encoder (512-dim). Fast + solid for semantic search.
    tfhub_model = "https://tfhub.dev/google/universal-sentence-encoder/4"
    batch_size = 64

    ensure_dir(out_dir)

    print(f"[load] chunks from: {chunks_dir}")
    chunks = load_chunks_from_folder(chunks_dir)
    print(f"[load] usable chunks: {len(chunks)}")

    texts = [c.text for c in chunks]

    print(f"[model] loading: {tfhub_model}")
    model = hub.load(tfhub_model)

    all_vecs: List[np.ndarray] = []
    print("[embed] embedding chunks...")
    for batch in tqdm(list(batched(texts, batch_size))):
        # TF Hub model returns a Tensor with shape (B, 512)
        vecs = model(batch).numpy().astype(np.float32)
        all_vecs.append(vecs)

    vectors = np.vstack(all_vecs).astype(np.float32)
    vectors = l2_normalize(vectors)  # cosine via inner product

    dim = vectors.shape[1]
    print(f"[index] building FAISS IndexFlatIP (dim={dim}, n={vectors.shape[0]})")
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    print(f"[save] {index_path} (FAISS index file: your local vector store)")
    faiss.write_index(index, index_path)

    print(f"[save] {meta_path}")
    with open(meta_path, "w", encoding="utf-8") as f:
        for row, c in enumerate(chunks):
            f.write(
                json.dumps(
                    {
                        "row": row,
                        "id": c.id,
                        "metadata": c.metadata,
                        "text": c.text,  # keep for debugging; remove later if too big
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print("[done] index + meta saved.")


if __name__ == "__main__":
    main()
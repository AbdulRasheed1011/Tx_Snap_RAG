from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import numpy as np
from tqdm import tqdm
import tensorflow_hub as hub
import faiss


def l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms


def load_meta(meta_path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(meta_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Bad JSON in meta file on line {line_no}: {e}") from e
    if not rows:
        raise RuntimeError(f"Meta file is empty: {meta_path}")
    return rows


def search(
    index: faiss.Index,
    meta: List[Dict[str, Any]],
    model,
    query: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    # Embed query -> (1, 512)
    q = model([query]).numpy().astype(np.float32)
    q = l2_normalize(q)

    scores, row_ids = index.search(q, top_k)

    results: List[Dict[str, Any]] = []
    for score, row_id in zip(scores[0], row_ids[0]):
        if row_id < 0:
            continue
        hit = meta[int(row_id)]
        results.append(
            {
                "score": float(score),
                "row": int(row_id),
                "id": hit.get("id"),
                "metadata": hit.get("metadata", {}),
                "text": hit.get("text", ""),
            }
        )
    return results


def main() -> None:
    index_path = "artifacts/index/index.faiss"
    meta_path = "artifacts/index/meta.jsonl"

    # MUST match embed_index.py
    tfhub_model = "https://tfhub.dev/google/universal-sentence-encoder/4"

    print(f"[load] faiss index: {index_path}")
    index = faiss.read_index(index_path)

    print(f"[load] meta: {meta_path}")
    meta = load_meta(meta_path)

    print(f"[model] loading: {tfhub_model}")
    model = hub.load(tfhub_model)

    print("\nType a question and press Enter. Type 'exit' to quit.\n")

    while True:
        query = input("query> ").strip()
        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            break

        results = search(index=index, meta=meta, model=model, query=query, top_k=5)

        print("\nTop matches:\n")
        for i, r in enumerate(results, start=1):
            md = r["metadata"] or {}
            snippet = r["text"].replace("\n", " ").strip()[:280]

            print(f"#{i}  score={r['score']:.4f}  row={r['row']}  id={r['id']}")
            print(f"    source_file={md.get('source_file')}  section={md.get('section')}")
            print(f"    chunk_file={md.get('chunk_file')}")
            print(f"    text: {snippet}...")
            print("")

        print("-" * 60)


if __name__ == "__main__":
    main()
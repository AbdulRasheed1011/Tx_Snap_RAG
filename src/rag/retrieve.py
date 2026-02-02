from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List
import numpy as np
import tensorflow_hub as hub
import faiss


def l2_normalize(x: np.ndarray) -> np.ndarray:
    """L2-normalize vectors row-wise."""
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms


@dataclass(frozen=True)
class Hit:
    score: float
    row: int
    id: str
    metadata: Dict[str, Any]
    text: str


class Retriever:
    """
    Loads FAISS index + metadata once and retrieves top-k chunks for a query.
    TFHub model is lazy-loaded to avoid startup failures.
    """

    def __init__(
        self,
        index_path: str = "artifacts/index/index.faiss",
        meta_path: str = "artifacts/index/meta.jsonl",
        tfhub_model: str = "https://tfhub.dev/google/universal-sentence-encoder/4",
        tfhub_cache_dir: str | None = None,
    ) -> None:
        self.index_path = index_path
        self.meta_path = meta_path
        self.tfhub_model = tfhub_model

        # Force safe TFHub behavior (avoid tar.gz corruption issues)
        os.environ.setdefault("TFHUB_MODEL_LOAD_FORMAT", "UNCOMPRESSED")

        # Optional: project-local TFHub cache
        if tfhub_cache_dir:
            os.environ["TFHUB_CACHE_DIR"] = tfhub_cache_dir

        # Load FAISS index and metadata
        self.index = faiss.read_index(self.index_path)
        self.meta = self._load_meta(self.meta_path)

        # Sanity check
        if len(self.meta) != self.index.ntotal:
            raise RuntimeError(
                f"Meta rows ({len(self.meta)}) != FAISS vectors ({self.index.ntotal}). "
                "Index and metadata are out of sync. Re-run embed_index.py."
            )

        # Lazy-loaded TFHub model
        self._model = None

    @staticmethod
    def _load_meta(meta_path: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        with open(meta_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"Bad JSON in meta on line {line_no}: {e}") from e
        if not rows:
            raise RuntimeError(f"Meta file is empty: {meta_path}")
        return rows

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            self._model = hub.load(self.tfhub_model)
            return self._model
        except Exception as e:
            raise RuntimeError(
                "Failed to load TFHub embedding model. "
                "Likely causes: blocked internet/proxy, corrupted cache, or SSL issues. "
                f"Handle: {self.tfhub_model}."
            ) from e

    def retrieve(self, query: str, top_k: int = 5) -> List[Hit]:
        model = self._get_model()

        # Embed query
        q = model([query]).numpy().astype(np.float32)
        q = l2_normalize(q)

        # FAISS search
        scores, row_ids = self.index.search(q, top_k)

        hits: List[Hit] = []
        for score, row_id in zip(scores[0], row_ids[0]):
            if row_id < 0:
                continue
            m = self.meta[int(row_id)]
            hits.append(
                Hit(
                    score=float(score),
                    row=int(row_id),
                    id=str(m.get("id", "")),
                    metadata=m.get("metadata", {}) or {},
                    text=str(m.get("text", "")),
                )
            )
        return hits
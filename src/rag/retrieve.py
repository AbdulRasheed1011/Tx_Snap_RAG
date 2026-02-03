from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import faiss
import numpy as np
from openai import OpenAI
from rank_bm25 import BM25Okapi

from src.core.settings import AppConfig


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x / norms


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Bad JSON in {path} on line {line_no}: {e}") from e
    return rows


@dataclass(frozen=True)
class Hit:
    score: float
    row: int
    id: str
    metadata: Dict[str, Any]
    text: str
    dense_score: float = 0.0
    bm25_score: float = 0.0
    coverage: float = 0.0


@dataclass(frozen=True)
class RetrievalResult:
    hits: List[Hit]
    mode: str
    should_answer: bool
    reason: str


class Retriever:
    """Hybrid retriever: dense + BM25 fusion, reranking, and confidence gating."""

    def __init__(
        self,
        *,
        index_path: str = "artifacts/index/index.faiss",
        meta_path: str = "artifacts/index/meta.jsonl",
        chunks_path: str = "data/chunks/chunks.jsonl",
        config_path: str = "config.yaml",
        embedding_model: str | None = None,
    ) -> None:
        cfg = AppConfig.load(config_path)
        if cfg.embedding.provider != "openai":
            raise ValueError(f"Unsupported embedding provider: {cfg.embedding.provider}")

        self.embedding_model = embedding_model or cfg.embedding.model
        self.default_min_score = float(cfg.retrieval.min_score)

        self.meta_rows = _read_jsonl(Path(meta_path))
        self.chunk_rows = _read_jsonl(Path(chunks_path))
        if not self.meta_rows and not self.chunk_rows:
            raise RuntimeError("No retrieval corpus found. Build chunks or FAISS metadata first.")

        self.meta_by_id: Dict[str, Dict[str, Any]] = {
            str(r.get("id", "")).strip(): r for r in self.meta_rows if str(r.get("id", "")).strip()
        }
        self.chunk_by_id: Dict[str, Dict[str, Any]] = {
            str(r.get("chunk_id", "")).strip(): r for r in self.chunk_rows if str(r.get("chunk_id", "")).strip()
        }

        self.client = OpenAI() if os.getenv("OPENAI_API_KEY") else None
        self.index = None
        index_file = Path(index_path)
        if index_file.exists() and self.meta_rows:
            self.index = faiss.read_index(str(index_file))
            if len(self.meta_rows) != self.index.ntotal:
                raise RuntimeError(
                    f"Meta rows ({len(self.meta_rows)}) != FAISS vectors ({self.index.ntotal}). "
                    "Re-run src/rag/embed_index.py."
                )

        self.bm25_ids: List[str] = []
        self.bm25_payloads: List[Dict[str, Any]] = []
        bm25_tokens: List[List[str]] = []

        if self.chunk_rows:
            for row in self.chunk_rows:
                chunk_id = str(row.get("chunk_id", "")).strip()
                text = str(row.get("text", "")).strip()
                if not chunk_id or not text:
                    continue
                payload = self._payload_from_chunk_row(row)
                self.bm25_ids.append(chunk_id)
                self.bm25_payloads.append(payload)
                bm25_tokens.append(_tokenize(text))
        else:
            for row in self.meta_rows:
                chunk_id = str(row.get("id", "")).strip()
                text = str(row.get("text", "")).strip()
                if not chunk_id or not text:
                    continue
                payload = self._payload_from_meta_row(row)
                self.bm25_ids.append(chunk_id)
                self.bm25_payloads.append(payload)
                bm25_tokens.append(_tokenize(text))

        self.bm25 = BM25Okapi(bm25_tokens) if bm25_tokens else None

    @staticmethod
    def _payload_from_chunk_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(row.get("chunk_id", "")),
            "metadata": {
                "doc_id": row.get("doc_id"),
                "url": row.get("url"),
                "kind": row.get("kind"),
                "start_char": row.get("start_char"),
                "end_char": row.get("end_char"),
                "token_estimate": row.get("token_estimate"),
                "created_at": row.get("created_at"),
            },
            "text": str(row.get("text", "")),
        }

    @staticmethod
    def _payload_from_meta_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(row.get("id", "")),
            "metadata": row.get("metadata", {}) or {},
            "text": str(row.get("text", "")),
        }

    def _embed_query(self, query: str) -> np.ndarray:
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is not set for dense retrieval.")
        response = self.client.embeddings.create(model=self.embedding_model, input=[query])
        vector = np.asarray(response.data[0].embedding, dtype=np.float32).reshape(1, -1)
        return _l2_normalize(vector)

    def _payload_for_chunk_id(self, chunk_id: str) -> Dict[str, Any]:
        chunk_row = self.chunk_by_id.get(chunk_id)
        if chunk_row is not None:
            return self._payload_from_chunk_row(chunk_row)

        meta_row = self.meta_by_id.get(chunk_id)
        if meta_row is not None:
            return self._payload_from_meta_row(meta_row)

        return {"id": chunk_id, "metadata": {}, "text": ""}

    def _retrieve_dense(self, query: str, *, top_k: int, min_score: float) -> Dict[str, Dict[str, Any]]:
        if self.index is None or self.client is None:
            return {}

        q = self._embed_query(query)
        scores, row_ids = self.index.search(q, top_k)

        out: Dict[str, Dict[str, Any]] = {}
        for rank, (score, row_id) in enumerate(zip(scores[0], row_ids[0]), start=1):
            if row_id < 0:
                continue
            s = float(score)
            if s < min_score:
                continue
            meta_row = self.meta_rows[int(row_id)]
            chunk_id = str(meta_row.get("id", "")).strip()
            if not chunk_id:
                continue
            out[chunk_id] = {
                "dense_score": s,
                "dense_rank": rank,
                "payload": self._payload_for_chunk_id(chunk_id),
                "row": int(row_id),
            }
        return out

    def _retrieve_bm25(self, query: str, *, top_k: int) -> Dict[str, Dict[str, Any]]:
        if self.bm25 is None:
            return {}

        query_tokens = _tokenize(query)
        if not query_tokens:
            return {}

        scores = self.bm25.get_scores(query_tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        out: Dict[str, Dict[str, Any]] = {}
        for rank, (row, score) in enumerate(ranked, start=1):
            chunk_id = self.bm25_ids[row]
            out[chunk_id] = {
                "bm25_score": float(score),
                "bm25_rank": rank,
                "payload": self.bm25_payloads[row],
                "row": int(row),
            }
        return out

    @staticmethod
    def _coverage(query_tokens: List[str], text_tokens: List[str]) -> float:
        if not query_tokens:
            return 0.0
        q = set(query_tokens)
        if not q:
            return 0.0
        t = set(text_tokens)
        return len(q & t) / len(q)

    def _fuse_and_rerank(
        self,
        *,
        query: str,
        dense_hits: Dict[str, Dict[str, Any]],
        bm25_hits: Dict[str, Dict[str, Any]],
        top_k: int,
    ) -> List[Hit]:
        merged: Dict[str, Dict[str, Any]] = {}
        for chunk_id, fields in dense_hits.items():
            merged.setdefault(chunk_id, {}).update(fields)
        for chunk_id, fields in bm25_hits.items():
            merged.setdefault(chunk_id, {}).update(fields)
        if not merged:
            return []

        max_dense = max((float(v.get("dense_score", 0.0)) for v in merged.values()), default=0.0) or 1.0
        max_bm25 = max((float(v.get("bm25_score", 0.0)) for v in merged.values()), default=0.0) or 1.0
        query_tokens = _tokenize(query)

        scored: List[Hit] = []
        for chunk_id, feats in merged.items():
            dense_score = float(feats.get("dense_score", 0.0))
            bm25_score = float(feats.get("bm25_score", 0.0))
            dense_rank = int(feats.get("dense_rank", 10_000))
            bm25_rank = int(feats.get("bm25_rank", 10_000))
            payload = feats.get("payload", {}) or {}
            text = str(payload.get("text", ""))
            coverage = self._coverage(query_tokens, _tokenize(text))

            rrf_score = 0.0
            if "dense_rank" in feats:
                rrf_score += _rrf(dense_rank)
            if "bm25_rank" in feats:
                rrf_score += _rrf(bm25_rank)

            dense_norm = dense_score / max_dense
            bm25_norm = bm25_score / max_bm25
            final_score = (0.35 * rrf_score) + (0.30 * dense_norm) + (0.20 * bm25_norm) + (0.15 * coverage)

            scored.append(
                Hit(
                    score=final_score,
                    row=int(feats.get("row", -1)),
                    id=chunk_id,
                    metadata=payload.get("metadata", {}) or {},
                    text=text,
                    dense_score=dense_score,
                    bm25_score=bm25_score,
                    coverage=coverage,
                )
            )

        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _confidence_gate(hits: List[Hit], *, mode: str, min_score: float) -> tuple[bool, str]:
        if not hits:
            return False, "no_candidates"

        top = hits[0]
        second_score = hits[1].score if len(hits) > 1 else 0.0
        margin = top.score - second_score

        lexical_ok = top.coverage >= 0.12 or top.bm25_score > 0.0
        dense_ok = top.dense_score >= min_score

        if mode == "bm25-only":
            if not lexical_ok:
                return False, "low_lexical_support"
            return True, "ok"

        if mode == "dense-only":
            if not dense_ok and top.coverage < 0.08:
                return False, "low_dense_support"
            return True, "ok"

        # hybrid
        if not lexical_ok and not dense_ok:
            return False, "low_hybrid_support"
        if margin < 0.001 and top.coverage < 0.10 and top.dense_score < (min_score + 0.03):
            return False, "ambiguous_top_hit"
        return True, "ok"

    def retrieve_with_result(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float | None = None,
        candidate_pool: int = 25,
    ) -> RetrievalResult:
        threshold = self.default_min_score if min_score is None else float(min_score)
        dense = self._retrieve_dense(query, top_k=max(top_k, candidate_pool), min_score=threshold)
        bm25 = self._retrieve_bm25(query, top_k=max(top_k, candidate_pool))

        if dense and bm25:
            mode = "hybrid"
        elif dense:
            mode = "dense-only"
        elif bm25:
            mode = "bm25-only"
        else:
            mode = "none"

        hits = self._fuse_and_rerank(query=query, dense_hits=dense, bm25_hits=bm25, top_k=top_k)
        should_answer, reason = self._confidence_gate(hits, mode=mode, min_score=threshold)
        return RetrievalResult(hits=hits, mode=mode, should_answer=should_answer, reason=reason)

    def retrieve(self, query: str, top_k: int = 5, min_score: float | None = None) -> List[Hit]:
        return self.retrieve_with_result(query, top_k=top_k, min_score=min_score).hits

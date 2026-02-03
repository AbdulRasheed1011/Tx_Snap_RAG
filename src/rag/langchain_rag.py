from __future__ import annotations

import json
import os
import re
import textwrap
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from src.core.settings import AppConfig

try:
    from langchain_ollama import OllamaLLM as _OllamaLLM  # type: ignore[import-not-found]

    _USING_LEGACY_OLLAMA = False
except ImportError:
    from langchain_community.llms import Ollama as _OllamaLLM

    _USING_LEGACY_OLLAMA = True


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {line_no} in {path}: {e}") from e
    return rows


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _coverage(query: str, text: str) -> float:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return 0.0
    text_tokens = set(_tokenize(text))
    return len(query_tokens & text_tokens) / len(query_tokens)


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _ollama_base_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return "http://localhost:11434"
    return urlunparse(parsed._replace(path="", params="", query="", fragment=""))


def _to_document(row: Dict[str, Any]) -> Document | None:
    text = str(row.get("text", "")).strip()
    chunk_id = str(row.get("chunk_id", "")).strip()
    if not text or not chunk_id:
        return None

    metadata: Dict[str, Any] = {
        "chunk_id": chunk_id,
        "doc_id": str(row.get("doc_id", "")),
        "url": str(row.get("url", "")),
        "kind": str(row.get("kind", "")),
        "start_char": int(row.get("start_char", 0) or 0),
        "end_char": int(row.get("end_char", 0) or 0),
        "token_estimate": int(row.get("token_estimate", 0) or 0),
        "created_at": str(row.get("created_at", "")),
    }
    return Document(page_content=text, metadata=metadata)


def _to_document_from_meta_row(row: Dict[str, Any]) -> Document | None:
    chunk_id = str(row.get("id", "")).strip()
    text = str(row.get("text", "")).strip()
    if not chunk_id or not text:
        return None

    raw_md = row.get("metadata", {}) or {}
    metadata: Dict[str, Any] = {
        "chunk_id": chunk_id,
        "doc_id": str(raw_md.get("doc_id", "")),
        "url": str(raw_md.get("url", "")),
        "kind": str(raw_md.get("kind", "")),
        "start_char": int(raw_md.get("start_char", 0) or 0),
        "end_char": int(raw_md.get("end_char", 0) or 0),
        "token_estimate": int(raw_md.get("token_estimate", 0) or 0),
        "created_at": str(raw_md.get("created_at", "")),
    }
    return Document(page_content=text, metadata=metadata)


def _format_context(docs: List[Document], max_chars_per_chunk: int = 1200) -> str:
    blocks: List[str] = []
    for i, doc in enumerate(docs, start=1):
        md = doc.metadata or {}
        text = doc.page_content.strip().replace("\n", " ")
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rstrip() + " ..."
        blocks.append(
            f"[{i}] doc_id={md.get('doc_id')} span={md.get('start_char')}-{md.get('end_char')} "
            f"url={md.get('url')}\n{text}\n"
        )
    return "\n".join(blocks)


@dataclass(frozen=True)
class LangChainCitation:
    cite: str
    score: float
    chunk_id: str
    text: str
    metadata: Dict[str, Any]
    dense_score: float | None
    bm25_score: float | None
    coverage: float


@dataclass(frozen=True)
class LangChainRagResult:
    answer: str
    citations: List[LangChainCitation]
    mode: str
    should_answer: bool
    reason: str
    retrieval_seconds: float
    generation_seconds: float
    total_seconds: float


class LangChainRAG:
    def __init__(
        self,
        *,
        config_path: str = "config.yaml",
        chunks_path: str = "data/chunks/chunks.jsonl",
        index_path: str = "artifacts/index/index.faiss",
        meta_path: str = "artifacts/index/meta.jsonl",
        ollama_url: str | None = None,
        ollama_model: str | None = None,
        disable_generation: bool = False,
    ) -> None:
        self.cfg = AppConfig.load(config_path)
        self.min_score = float(self.cfg.retrieval.min_score)
        self.disable_generation = disable_generation
        self.retrieval_mode = "langchain_bm25"
        self.hybrid_enabled = False
        self.hybrid_disabled_reason = ""

        chunk_file = Path(chunks_path)
        if not chunk_file.exists():
            raise FileNotFoundError(f"Chunks file not found: {chunk_file}")

        rows = _read_jsonl(chunk_file)
        docs: List[Document] = []
        self.docs_by_chunk_id: Dict[str, Document] = {}
        for row in rows:
            doc = _to_document(row)
            if doc is not None:
                docs.append(doc)
                self.docs_by_chunk_id[str(doc.metadata.get("chunk_id", ""))] = doc

        if not docs:
            raise RuntimeError(f"No usable chunks in {chunk_file}")

        self.bm25_retriever = BM25Retriever.from_documents(docs)
        self.bm25_retriever.k = max(self.cfg.retrieval.top_k, 1)

        self.vector_store = None
        if self.cfg.retrieval.hybrid:
            self._init_faiss_vector_retriever(index_path=index_path, meta_path=meta_path)
        else:
            self.hybrid_disabled_reason = "config_hybrid_disabled"

        model_name = ollama_model or os.getenv("OLLAMA_MODEL", "llama3.1")
        ollama_api = ollama_url or os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        base_url = _ollama_base_url(ollama_api)
        if _USING_LEGACY_OLLAMA:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.llm = _OllamaLLM(model=model_name, base_url=base_url, temperature=0.0)
        else:
            self.llm = _OllamaLLM(model=model_name, base_url=base_url, temperature=0.0)

        prompt = PromptTemplate.from_template(
            textwrap.dedent(
                """
                You are a careful assistant answering questions using ONLY the provided context.
                If the context does not contain the answer, say: "I don't have enough information in the provided documents."

                Rules:
                - Use only the context below.
                - Cite sources using bracket numbers like [1], [2].
                - Be concise and factual.

                Question:
                {question}

                Context:
                {context}

                Answer:
                """
            ).strip()
        )
        self.answer_chain = prompt | self.llm | StrOutputParser()

    def _init_faiss_vector_retriever(self, *, index_path: str, meta_path: str) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            self.hybrid_disabled_reason = "missing_openai_api_key"
            return

        index_file = Path(index_path)
        meta_file = Path(meta_path)
        if not index_file.exists() or not meta_file.exists():
            self.hybrid_disabled_reason = "missing_faiss_artifacts"
            return

        try:
            import faiss  # type: ignore[import-untyped]
            from langchain_community.docstore.in_memory import InMemoryDocstore
            from langchain_community.embeddings import OpenAIEmbeddings
            from langchain_community.vectorstores import FAISS
            from langchain_community.vectorstores.faiss import DistanceStrategy
        except Exception:
            self.hybrid_disabled_reason = "langchain_faiss_dependencies_unavailable"
            return

        try:
            meta_rows = _read_jsonl(meta_file)
            if not meta_rows:
                self.hybrid_disabled_reason = "empty_meta_rows"
                return

            index = faiss.read_index(str(index_file))
            embeddings = OpenAIEmbeddings(model=self.cfg.embedding.model)

            docstore_data: Dict[str, Document] = {}
            index_to_docstore_id: Dict[int, str] = {}
            for row in meta_rows:
                row_idx = int(row.get("row", -1))
                chunk_id = str(row.get("id", "")).strip()
                if row_idx < 0 or not chunk_id:
                    continue

                doc = self.docs_by_chunk_id.get(chunk_id)
                if doc is None:
                    doc = _to_document_from_meta_row(row)
                if doc is None:
                    continue

                docstore_data[chunk_id] = doc
                index_to_docstore_id[row_idx] = chunk_id

            if len(index_to_docstore_id) != index.ntotal:
                self.hybrid_disabled_reason = "faiss_meta_size_mismatch"
                return

            self.vector_store = FAISS(
                embedding_function=embeddings,
                index=index,
                docstore=InMemoryDocstore(docstore_data),
                index_to_docstore_id=index_to_docstore_id,
                distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
            )
            self.hybrid_enabled = True
            self.retrieval_mode = "langchain_hybrid"
            self.hybrid_disabled_reason = ""
        except Exception:
            self.hybrid_disabled_reason = "failed_to_load_faiss_vectorstore"
            self.vector_store = None
            self.hybrid_enabled = False

    @staticmethod
    def _failure_reason(base: str, fallback_reason: str) -> str:
        if fallback_reason:
            return f"{base}(fallback={fallback_reason})"
        return base

    def _vector_hits(self, query: str, *, top_k: int) -> List[tuple[Document, float, int]]:
        if self.vector_store is None:
            return []

        try:
            hits = self.vector_store.similarity_search_with_score(query, k=top_k)
        except Exception:
            self.hybrid_disabled_reason = "vector_query_failed"
            return []

        out: List[tuple[Document, float, int]] = []
        for rank, (doc, score) in enumerate(hits, start=1):
            try:
                dense_score = _clamp01(float(score))
            except Exception:
                dense_score = 0.0
            out.append((doc, dense_score, rank))
        return out

    def _retrieve_ranked(self, question: str, *, top_k: int) -> List[Dict[str, Any]]:
        self.bm25_retriever.k = top_k
        bm25_docs = self.bm25_retriever.invoke(question)

        merged: Dict[str, Dict[str, Any]] = {}

        for rank, doc in enumerate(bm25_docs, start=1):
            chunk_id = str((doc.metadata or {}).get("chunk_id", "")).strip()
            if not chunk_id:
                continue
            cov = _coverage(question, doc.page_content)
            entry = merged.setdefault(
                chunk_id,
                {
                    "doc": doc,
                    "coverage": 0.0,
                    "bm25_score": None,
                    "dense_score": None,
                    "bm25_rank": None,
                    "dense_rank": None,
                },
            )
            entry["doc"] = doc
            entry["coverage"] = max(float(entry["coverage"]), cov)
            entry["bm25_score"] = cov
            entry["bm25_rank"] = rank

        if self.hybrid_enabled:
            for doc, dense_score, rank in self._vector_hits(question, top_k=top_k):
                chunk_id = str((doc.metadata or {}).get("chunk_id", "")).strip()
                if not chunk_id:
                    continue
                cov = _coverage(question, doc.page_content)
                entry = merged.setdefault(
                    chunk_id,
                    {
                        "doc": doc,
                        "coverage": 0.0,
                        "bm25_score": None,
                        "dense_score": None,
                        "bm25_rank": None,
                        "dense_rank": None,
                    },
                )
                entry["doc"] = entry.get("doc") or doc
                entry["coverage"] = max(float(entry["coverage"]), cov)
                entry["dense_score"] = dense_score
                entry["dense_rank"] = rank

        ranked: List[Dict[str, Any]] = []
        for chunk_id, entry in merged.items():
            coverage = _clamp01(float(entry.get("coverage") or 0.0))
            bm25_score = entry.get("bm25_score")
            dense_score = entry.get("dense_score")
            bm25_rank = entry.get("bm25_rank")
            dense_rank = entry.get("dense_rank")

            if self.hybrid_enabled:
                bm25_component = _clamp01(float(bm25_score or 0.0))
                dense_component = _clamp01(float(dense_score or 0.0))
                rrf_component = 0.0
                if isinstance(bm25_rank, int):
                    rrf_component += 1.0 / (1.0 + bm25_rank)
                if isinstance(dense_rank, int):
                    rrf_component += 1.0 / (1.0 + dense_rank)
                final_score = (0.4 * bm25_component) + (0.4 * dense_component) + (0.2 * _clamp01(rrf_component))
            else:
                final_score = coverage

            ranked.append(
                {
                    "chunk_id": chunk_id,
                    "doc": entry["doc"],
                    "score": _clamp01(float(final_score)),
                    "dense_score": dense_score,
                    "bm25_score": bm25_score,
                    "coverage": coverage,
                }
            )

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked[:top_k]

    def answer(self, question: str, *, top_k: int | None = None) -> LangChainRagResult:
        t0 = time.perf_counter()
        k = max(top_k or self.cfg.retrieval.top_k, 1)

        t_retrieval0 = time.perf_counter()
        ranked = self._retrieve_ranked(question, top_k=k)
        retrieval_seconds = time.perf_counter() - t_retrieval0

        fallback_reason = self.hybrid_disabled_reason if (self.cfg.retrieval.hybrid and not self.hybrid_enabled) else ""

        if not ranked:
            return LangChainRagResult(
                answer="I don't have enough information in the provided documents.",
                citations=[],
                mode=self.retrieval_mode,
                should_answer=False,
                reason=self._failure_reason("no_hits", fallback_reason),
                retrieval_seconds=retrieval_seconds,
                generation_seconds=0.0,
                total_seconds=time.perf_counter() - t0,
            )

        best_score = float(ranked[0]["score"])
        if best_score < self.min_score:
            return LangChainRagResult(
                answer="I don't have enough information in the provided documents.",
                citations=[],
                mode=self.retrieval_mode,
                should_answer=False,
                reason=self._failure_reason(f"low_confidence(best_score={best_score:.3f})", fallback_reason),
                retrieval_seconds=retrieval_seconds,
                generation_seconds=0.0,
                total_seconds=time.perf_counter() - t0,
            )

        ordered_docs = [item["doc"] for item in ranked]
        context_block = _format_context(ordered_docs)

        t_generation0 = time.perf_counter()
        if self.disable_generation:
            answer_text = "(generation disabled)"
        else:
            answer_text = self.answer_chain.invoke({"question": question, "context": context_block}).strip()
            if not answer_text:
                answer_text = "I don't have enough information in the provided documents."
        generation_seconds = time.perf_counter() - t_generation0

        citations: List[LangChainCitation] = []
        for i, item in enumerate(ranked, start=1):
            doc = item["doc"]
            md = doc.metadata or {}
            citations.append(
                LangChainCitation(
                    cite=f"[{i}]",
                    score=float(item["score"]),
                    chunk_id=str(md.get("chunk_id", "")),
                    text=doc.page_content,
                    metadata=md,
                    dense_score=float(item["dense_score"]) if item["dense_score"] is not None else None,
                    bm25_score=float(item["bm25_score"]) if item["bm25_score"] is not None else None,
                    coverage=float(item["coverage"]),
                )
            )

        return LangChainRagResult(
            answer=answer_text,
            citations=citations,
            mode=self.retrieval_mode,
            should_answer=True,
            reason="ok" if not fallback_reason else f"ok(fallback={fallback_reason})",
            retrieval_seconds=retrieval_seconds,
            generation_seconds=generation_seconds,
            total_seconds=time.perf_counter() - t0,
        )

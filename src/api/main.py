from __future__ import annotations

import os
import textwrap
import time
from typing import Any, Dict, List

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from src.api.metrics import ANSWER_ATTEMPTS_TOTAL, REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL
from src.api.models import AnswerRequest, AnswerResponse, Citation, Timing
from src.api.ollama_client import generate as ollama_generate
from src.api.ollama_client import is_model_ready
from src.api.settings import ApiSettings
from src.core.logging import get_logger
from src.core.settings import AppConfig
from src.rag.retrieve import RetrievalResult, Retriever

logger = get_logger("api")

def _parse_csv(value: str) -> List[str]:
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def _load_settings() -> ApiSettings:
    cors_raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    cors_allow_origins: List[str] = []
    if cors_raw:
        cors_allow_origins = _parse_csv(cors_raw)

    return ApiSettings(
        config_path=os.getenv("RAG_CONFIG_PATH", "config.yaml"),
        chunks_path=os.getenv("RAG_CHUNKS_PATH", "data/chunks/chunks.jsonl"),
        index_path=os.getenv("RAG_INDEX_PATH", "artifacts/index/index.faiss"),
        meta_path=os.getenv("RAG_META_PATH", "artifacts/index/meta.jsonl"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        ollama_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")),
        api_key=os.getenv("API_KEY") or None,
        cors_allow_origins=cors_allow_origins,
        disable_generation=os.getenv("RAG_DISABLE_GENERATION", "false").lower() in {"1", "true", "yes"},
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def _build_prompt(question: str, context_block: str) -> str:
    return textwrap.dedent(
        f"""
        You are a careful assistant answering questions using ONLY the provided context.
        If the context does not contain the answer, say: "I don't have enough information in the provided documents."

        Rules:
        - Use only the context below.
        - Cite sources using bracket numbers like [1], [2] after the sentence they support.
        - Be concise and factual.

        Question:
        {question}

        Context:
        {context_block}

        Answer:
        """
    ).strip()


def _format_context(hits: list[dict[str, Any]], max_chars_per_chunk: int = 1200) -> str:
    blocks: List[str] = []
    for h in hits:
        md = h.get("metadata") or {}
        cite = h.get("cite", "[?]")
        doc_id = md.get("doc_id", "unknown_doc")
        span = f"{md.get('start_char', 0)}-{md.get('end_char', 0)}"
        url = md.get("url", "")
        chunk_text = str(h.get("text", "")).strip().replace("\n", " ")
        if len(chunk_text) > max_chars_per_chunk:
            chunk_text = chunk_text[:max_chars_per_chunk].rstrip() + " ..."
        blocks.append(f"{cite} doc_id={doc_id} span={span} url={url}\n{chunk_text}\n")
    return "\n".join(blocks)


def create_app() -> FastAPI:
    settings = _load_settings()

    application = FastAPI(title="Tx_Snap_RAG API", version="0.1.0")

    if settings.cors_allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @application.on_event("startup")
    def _startup() -> None:
        logger.setLevel(settings.log_level)
        application.state.settings = settings
        application.state.startup_error = None
        try:
            application.state.cfg = AppConfig.load(settings.config_path)
            application.state.retriever = Retriever(
                index_path=settings.index_path,
                meta_path=settings.meta_path,
                chunks_path=settings.chunks_path,
                config_path=settings.config_path,
            )
            logger.info("startup_complete")
        except Exception as e:
            application.state.startup_error = str(e)
            application.state.cfg = None
            application.state.retriever = None
            logger.exception(f"startup_failed error={e}")

    @application.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readyz() -> Dict[str, Any]:
        startup_error: str | None = application.state.startup_error
        cfg: AppConfig | None = application.state.cfg
        if startup_error:
            return {
                "ready": False,
                "error": startup_error,
                "config_path": settings.config_path,
                "chunks_path": settings.chunks_path,
                "index_path": settings.index_path,
                "meta_path": settings.meta_path,
                "ollama_url": settings.ollama_url,
                "ollama_model": settings.ollama_model,
            }

        ollama_ok, ollama_detail = (True, "generation_disabled")
        if not settings.disable_generation:
            ollama_ok, ollama_detail = is_model_ready(
                url=settings.ollama_url,
                model=settings.ollama_model,
                timeout_seconds=2,
            )

        return {
            "ready": ollama_ok,
            "config_path": settings.config_path,
            "chunks_path": settings.chunks_path,
            "index_path": settings.index_path,
            "meta_path": settings.meta_path,
            "retrieval_top_k": cfg.retrieval.top_k if cfg else None,
            "retrieval_min_score": cfg.retrieval.min_score if cfg else None,
            "ollama_url": settings.ollama_url,
            "ollama_model": settings.ollama_model,
            "ollama_status": ollama_detail,
            "dense_enabled": bool(os.getenv("OPENAI_API_KEY")),
        }

    @application.get("/metrics")
    def metrics() -> Response:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    @application.post("/answer", response_model=AnswerResponse)
    def answer(
        req: AnswerRequest,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> AnswerResponse:
        startup_error: str | None = application.state.startup_error
        if startup_error:
            REQUESTS_TOTAL.labels(endpoint="/answer", status="503").inc()
            raise HTTPException(status_code=503, detail=f"Service is not ready: {startup_error}")

        if settings.api_key and x_api_key != settings.api_key:
            REQUESTS_TOTAL.labels(endpoint="/answer", status="401").inc()
            raise HTTPException(status_code=401, detail="Unauthorized")

        t0 = time.perf_counter()
        cfg: AppConfig = application.state.cfg
        retriever: Retriever = application.state.retriever

        top_k = req.top_k or cfg.retrieval.top_k

        with REQUEST_LATENCY_SECONDS.labels(endpoint="/answer").time():
            # Retrieval
            t_retrieve0 = time.perf_counter()
            retrieval: RetrievalResult = retriever.retrieve_with_result(
                req.question,
                top_k=top_k,
                min_score=cfg.retrieval.min_score,
            )
            retrieval_sec = time.perf_counter() - t_retrieve0

            ANSWER_ATTEMPTS_TOTAL.labels(
                retrieval_mode=retrieval.mode,
                should_answer=str(retrieval.should_answer).lower(),
            ).inc()

            if not retrieval.hits or not retrieval.should_answer:
                REQUESTS_TOTAL.labels(endpoint="/answer", status="200").inc()
                total_sec = time.perf_counter() - t0
                return AnswerResponse(
                    answer="I don't have enough information in the provided documents.",
                    citations=[],
                    retrieval={
                        "mode": retrieval.mode,
                        "should_answer": retrieval.should_answer,
                        "reason": retrieval.reason,
                        "top_k": top_k,
                    },
                    timing=Timing(
                        retrieval_seconds=retrieval_sec,
                        generation_seconds=0.0,
                        total_seconds=total_sec,
                    ),
                )

            hits_payload: list[dict[str, Any]] = []
            citations: List[Citation] = []
            for i, hit in enumerate(retrieval.hits, start=1):
                md = hit.metadata or {}
                cite = f"[{i}]"
                hits_payload.append({"cite": cite, "text": hit.text, "metadata": md})
                citations.append(
                    Citation(
                        cite=cite,
                        score=hit.score,
                        chunk_id=hit.id,
                        doc_id=md.get("doc_id"),
                        url=md.get("url"),
                        start_char=md.get("start_char"),
                        end_char=md.get("end_char"),
                        retrieval_mode=retrieval.mode,
                        dense_score=hit.dense_score,
                        bm25_score=hit.bm25_score,
                        coverage=hit.coverage,
                    )
                )

            # Generation
            context_block = _format_context(hits_payload)
            prompt = _build_prompt(req.question, context_block)

            t_gen0 = time.perf_counter()
            if settings.disable_generation:
                answer_text = "(generation disabled)"
            else:
                try:
                    answer_text = ollama_generate(
                        url=settings.ollama_url,
                        model=settings.ollama_model,
                        prompt=prompt,
                        timeout_seconds=settings.ollama_timeout_seconds,
                    )
                except Exception as e:
                    REQUESTS_TOTAL.labels(endpoint="/answer", status="500").inc()
                    raise HTTPException(status_code=500, detail=f"Ollama generation failed: {e}") from e
            gen_sec = time.perf_counter() - t_gen0

            REQUESTS_TOTAL.labels(endpoint="/answer", status="200").inc()
            total_sec = time.perf_counter() - t0

            return AnswerResponse(
                answer=answer_text,
                citations=citations,
                retrieval={
                    "mode": retrieval.mode,
                    "should_answer": retrieval.should_answer,
                    "reason": retrieval.reason,
                    "top_k": top_k,
                },
                timing=Timing(
                    retrieval_seconds=retrieval_sec,
                    generation_seconds=gen_sec,
                    total_seconds=total_sec,
                ),
            )

    return application


app = create_app()

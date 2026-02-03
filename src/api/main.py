from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from src.api.metrics import ANSWER_ATTEMPTS_TOTAL, REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL
from src.api.models import AnswerRequest, AnswerResponse, Citation, Timing
from src.api.ollama_client import is_model_ready
from src.api.settings import ApiSettings
from src.core.logging import get_logger
from src.rag.langchain_rag import LangChainRAG

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


def create_app() -> FastAPI:
    settings = _load_settings()

    application = FastAPI(title="Tx_Snap_RAG API", version="0.2.0")

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
            application.state.rag_engine = LangChainRAG(
                config_path=settings.config_path,
                chunks_path=settings.chunks_path,
                index_path=settings.index_path,
                meta_path=settings.meta_path,
                ollama_url=settings.ollama_url,
                ollama_model=settings.ollama_model,
                disable_generation=settings.disable_generation,
            )
            logger.info("startup_complete")
        except Exception as e:
            application.state.startup_error = str(e)
            application.state.rag_engine = None
            logger.exception(f"startup_failed error={e}")

    @application.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readyz() -> Dict[str, Any]:
        startup_error: str | None = application.state.startup_error
        rag_engine: LangChainRAG | None = application.state.rag_engine
        if startup_error:
            return {
                "ready": False,
                "error": startup_error,
                "config_path": settings.config_path,
                "chunks_path": settings.chunks_path,
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
            "retrieval_top_k": rag_engine.cfg.retrieval.top_k if rag_engine else None,
            "retrieval_min_score": rag_engine.min_score if rag_engine else None,
            "retrieval_mode": rag_engine.retrieval_mode if rag_engine else None,
            "hybrid_enabled": rag_engine.hybrid_enabled if rag_engine else None,
            "hybrid_disabled_reason": rag_engine.hybrid_disabled_reason if rag_engine else None,
            "ollama_url": settings.ollama_url,
            "ollama_model": settings.ollama_model,
            "ollama_status": ollama_detail,
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

        rag_engine: LangChainRAG | None = application.state.rag_engine
        if rag_engine is None:
            REQUESTS_TOTAL.labels(endpoint="/answer", status="503").inc()
            raise HTTPException(status_code=503, detail="Service is not ready: RAG engine is not initialized.")

        with REQUEST_LATENCY_SECONDS.labels(endpoint="/answer").time():
            result = rag_engine.answer(req.question, top_k=req.top_k)

            ANSWER_ATTEMPTS_TOTAL.labels(
                retrieval_mode=result.mode,
                should_answer=str(result.should_answer).lower(),
            ).inc()

            citations: List[Citation] = []
            for c in result.citations:
                md = c.metadata or {}
                citations.append(
                    Citation(
                        cite=c.cite,
                        score=c.score,
                        chunk_id=c.chunk_id,
                        doc_id=md.get("doc_id"),
                        url=md.get("url"),
                        start_char=md.get("start_char"),
                        end_char=md.get("end_char"),
                        retrieval_mode=result.mode,
                        dense_score=c.dense_score,
                        bm25_score=c.bm25_score,
                        coverage=c.coverage,
                    )
                )

            REQUESTS_TOTAL.labels(endpoint="/answer", status="200").inc()
            return AnswerResponse(
                answer=result.answer,
                citations=citations,
                retrieval={
                    "mode": result.mode,
                    "should_answer": result.should_answer,
                    "reason": result.reason,
                    "top_k": req.top_k or rag_engine.cfg.retrieval.top_k,
                },
                timing=Timing(
                    retrieval_seconds=result.retrieval_seconds,
                    generation_seconds=result.generation_seconds,
                    total_seconds=result.total_seconds,
                ),
            )

    return application


app = create_app()

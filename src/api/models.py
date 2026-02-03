from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: Optional[int] = Field(default=None, gt=0)


class Citation(BaseModel):
    cite: str
    score: float
    chunk_id: str
    doc_id: str | None = None
    url: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    retrieval_mode: str | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    coverage: float | None = None


class Timing(BaseModel):
    retrieval_seconds: float
    generation_seconds: float
    total_seconds: float


class AnswerResponse(BaseModel):
    answer: str
    citations: List[Citation]
    retrieval: Dict[str, Any]
    timing: Timing


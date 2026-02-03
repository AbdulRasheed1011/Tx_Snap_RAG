from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, HttpUrl
from pathlib import Path
import yaml


# -----------------------------
# Project metadata
# -----------------------------
class ProjectConfig(BaseModel):
    name: str
    description: str
    jurisdiction: str
    domain: str


# -----------------------------
# Source crawling config
# -----------------------------
class SourcesConfig(BaseModel):
    allowed_patterns: List[str]
    deny_patterns: List[str]
    allowed_domains: List[str]
    seed_urls: List[HttpUrl]


class IngestionConfig(BaseModel):
    crawl_depth: int = Field(ge=0, le=5)
    timeout_seconds: int = Field(gt=0, le=60)
    max_pages: int = Field(gt=0)
    user_agent: str
    max_pdfs_per_page: int = Field(ge=0)
    max_pdf_mb: int = Field(gt=0)


class PdfConfig(BaseModel):
    enabled: bool = True
    extract_method: Literal["pypdf", "pymupdf"] = "pypdf"


# -----------------------------
# Chunking / Embedding
# -----------------------------
class ChunkingConfig(BaseModel):
    method: Literal["fixed", "recursive", "heading"]
    min_tokens: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    overlap_tokens: int = Field(ge=0)


class EmbeddingConfig(BaseModel):
    provider: Literal["openai"]
    model: str
    batch_size: int = Field(gt=0)


# -----------------------------
# Retrieval / Generation
# -----------------------------
class RetrievalConfig(BaseModel):
    top_k: int = Field(gt=0)
    min_score: float = Field(ge=0.0, le=1.0)
    hybrid: bool = True


class GenerationConfig(BaseModel):
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=1.0)
    require_citations: bool = True


# -----------------------------
# Root settings object
# -----------------------------
class AppConfig(BaseModel):
    project: ProjectConfig
    sources: SourcesConfig
    ingestion: IngestionConfig
    pdf: PdfConfig
    chunking: ChunkingConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        return cls.model_validate(raw)
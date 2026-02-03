from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ApiSettings(BaseModel):
    # Paths
    config_path: str = Field(default="config.yaml")
    chunks_path: str = Field(default="data/chunks/chunks.jsonl")
    index_path: str = Field(default="artifacts/index/index.faiss")
    meta_path: str = Field(default="artifacts/index/meta.jsonl")

    # Ollama
    ollama_url: str = Field(default="http://localhost:11434/api/generate")
    ollama_model: str = Field(default="llama3.1")
    ollama_timeout_seconds: int = Field(default=180, gt=0)

    # Public API controls
    api_key: Optional[str] = Field(default=None)
    cors_allow_origins: List[str] = Field(default_factory=list)

    # Serving behavior
    disable_generation: bool = Field(default=False)

    # Operational
    log_level: str = Field(default="INFO")

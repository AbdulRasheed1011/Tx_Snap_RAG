#!/usr/bin/env bash
set -euo pipefail

export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export RAG_CONFIG_PATH="${RAG_CONFIG_PATH:-config.yaml}"
export RAG_CHUNKS_PATH="${RAG_CHUNKS_PATH:-data/chunks/chunks.jsonl}"
export RAG_INDEX_PATH="${RAG_INDEX_PATH:-artifacts/index/index.faiss}"
export RAG_META_PATH="${RAG_META_PATH:-artifacts/index/meta.jsonl}"

export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434/api/generate}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1}"
export REQUIRE_API_KEY="${REQUIRE_API_KEY:-false}"

exec uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"

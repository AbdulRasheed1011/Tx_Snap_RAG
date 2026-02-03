# Tx_Snap_RAG
**Retrieval-Augmented Generation (RAG) System for Texas SNAP (HHSC)**

## Overview

Tx_Snap_RAG is a production-oriented Retrieval-Augmented Generation (RAG) pipeline designed to ingest, normalize, and prepare authoritative Texas SNAP (HHSC) policy content for reliable downstream retrieval and LLM-based question answering.

The system is engineered with **incremental processing, strong data contracts, and operational observability**

---

## System Architecture

```
config.yaml
   │
   ▼
data_main.py     # Pipeline orchestrator
   │
   ├── fetch.py   # Controlled web ingestion (HTML + PDFs) -> data/raw + fetch_manifest.jsonl
   │
   ├── pages.py   # Cleaning + organization -> data/processed + data/organized/docs.jsonl
   │
   └── chunk.py   # Chunking -> data/chunks/chunks.jsonl
        │
        ▼
retrieval + generation
   ├── retrieve.py      # Hybrid retrieval (FAISS + BM25) + rerank + confidence gating
   ├── embed_index.py   # (Optional) Build FAISS index (requires OpenAI embeddings)
   └── main.py          # RAG CLI: Ollama-first generation + timing (+ OpenAI fallback if configured)
```

`data_main.py` acts solely as a **pipeline orchestrator**, coordinating stages without embedding business logic. Each stage is independently testable and idempotent.

---

## Engineering Principles

### Configuration-First Design
All runtime behavior is driven via `config.yaml`, including:
- crawl scope and safety rules
- chunk sizing and overlap
- downstream embedding and retrieval parameters

This enables controlled system evolution without code changes.

### Incremental & Idempotent Processing
Each pipeline stage avoids unnecessary recomputation:
- Fetch reuses existing raw artifacts by default (skip-if-present)
- Organize/Chunking are stable and reproducible across reruns

This design supports frequent re-runs and policy updates with minimal cost.

### Explicit Data Contracts
Inter-stage boundaries are enforced using Pydantic models (e.g., `OrganizedDoc`, `ChunkRecord`), preventing silent schema drift and ensuring downstream correctness.

### Observability by Default
All stages emit structured logs capturing:
- stage lifecycle events
- processed vs skipped counts
- malformed or missing data warnings

Logs are suitable for local debugging or centralized monitoring systems.

---

## Repository Layout

```
Tx_Snap_RAG/
├── data_main.py              # Pipeline entrypoint
├── main.py                   # RAG CLI (retrieval + answer + timing)
├── config.yaml               # Declarative configuration
│
├── src/
│   ├── core/
│   │   ├── logging.py        # Centralized logging
│   │   ├── settings.py       # Config loading & validation
│   │   └── context.py        # run_id generation
│   │
│   └── ingest/
│       ├── fetch.py          # Web & PDF ingestion
│       ├── pages.py          # Text cleaning & organization
│       └── chunk.py          # Chunking logic
│
│   └── rag/
│       ├── embed_index.py    # Build FAISS index (OpenAI embeddings)
│       ├── retrieve.py       # Hybrid retrieval + rerank + gating
│       ├── query_index.py    # Retrieval debug CLI
│       └── rag_answer.py     # RAG answer CLI (Ollama)
│
├── data/
│   ├── raw/                  # Raw HTML & PDFs
│   ├── processed/            # Normalized text
│   ├── organized/            # Document index (docs.jsonl)
│   └── chunks/               # Chunked corpus
│
└── artifacts/
    ├── index/                # FAISS index + metadata
    └── logs/                 # Pipeline logs
```

---

## Pipeline Stages

### 1. Fetch — Web Ingestion
**Objective:** Reliably ingest authoritative SNAP policy content while minimizing unnecessary downloads.

**Key Capabilities:**
- domain and path allow/deny rules
- incremental fetch logic
- HTML and PDF support
- append-only ingestion manifest

**Outputs:**
- `data/raw/*.html`
- `data/raw/pdfs/*.pdf`
- `data/raw/fetch_manifest.jsonl`

---

### 2. Pages — Clean & Organize
**Objective:** Convert raw web artifacts into clean, model-consumable text while preserving provenance.

**Processing Includes:**
- boilerplate and navigation removal
- content normalization
- PDF text extraction
- document-level metadata indexing

**Outputs:**
- `data/processed/<doc_id>.txt`
- `data/organized/docs.jsonl`

---

### 3. Chunk — Retrieval Preparation
**Objective:** Prepare semantically coherent text chunks optimized for vector retrieval.

**Chunking Strategy:**
- paragraph-first segmentation
- sentence-based fallback for long sections
- overlapping windows to avoid boundary loss
- stable, hash-based chunk identifiers

**Outputs:**
- `data/chunks/chunks.jsonl`

---

## Quickstart

### 1) Run ingestion (build chunks)

```bash
.venv/bin/python data_main.py
```

This produces:
- `data/raw/fetch_manifest.jsonl`
- `data/organized/docs.jsonl`
- `data/chunks/chunks.jsonl`

### 2) (Optional) Build FAISS index (requires OpenAI embeddings)

```bash
export OPENAI_API_KEY="..."   # required for embeddings
.venv/bin/python -m src.rag.embed_index
```

Outputs:
- `artifacts/index/index.faiss`
- `artifacts/index/meta.jsonl`

### 3) Run retrieval debug CLI

```bash
.venv/bin/python -m src.rag.query_index
```

### 4) Run end-to-end RAG CLI (Ollama-first)

Start Ollama:
```bash
ollama serve
ollama pull llama3.1
```

Then run:
```bash
.venv/bin/python main.py
```

Environment variables:
- `OLLAMA_MODEL` (default: `llama3.1`)
- `OLLAMA_URL` (default: `http://localhost:11434/api/generate`)
- `OPENAI_API_KEY` (optional fallback for generation; also enables dense retrieval)

---

## Current Capabilities

- HTML and PDF ingestion
- Incremental, reproducible pipelines
- Clean text normalization
- Production-grade chunking
- Structured logging and schema validation
- BM25 retrieval (no API keys required)
- Hybrid retrieval (FAISS + BM25) with reranking + confidence gating (when FAISS index + OpenAI embeddings are available)
- Ollama-first grounded answer generation with citations (OpenAI optional fallback)

---

## Planned Extensions

- FastAPI inference service
- Retrieval and grounding evaluation
- Monitoring and drift detection

---

## Intent

This repository demonstrates how to design and maintain **RAG systems with production discipline**, emphasizing data quality, reproducibility, and operational reliability over one-off experimentation.

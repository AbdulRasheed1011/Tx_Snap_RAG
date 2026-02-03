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
fetch.py        # Controlled web ingestion (HTML + PDFs)
   │
   ▼
pages.py        # Cleaning, normalization, organization
   │
   ▼
chunk.py        # Structure-aware chunking
   │
   ▼
chunks.jsonl    # RAG-ready corpus
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
- Fetch detects unchanged content
- Organize skips previously processed documents
- Chunking is stable and reproducible

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
├── data/
│   ├── raw/                  # Raw HTML & PDFs
│   ├── processed/            # Normalized text
│   ├── organized/            # Document index (docs.jsonl)
│   └── chunks/               # Chunked corpus
│
└── artifacts/
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

## Running the Pipeline

```bash
python data_main.py
```

The pipeline executes fetch, clean, and chunk stages sequentially and emits structured logs for each stage.

---

## Current Capabilities

- HTML and PDF ingestion
- Incremental, reproducible pipelines
- Clean text normalization
- Production-grade chunking
- Structured logging and schema validation

---

## Planned Extensions

- Embedding generation (OpenAI or equivalent)
- Vector indexing (FAISS / hybrid retrieval)
- FastAPI inference service
- Retrieval and grounding evaluation
- Monitoring and drift detection

---

## Intent

This repository demonstrates how to design and maintain **RAG systems with production discipline**, emphasizing data quality, reproducibility, and operational reliability over one-off experimentation.
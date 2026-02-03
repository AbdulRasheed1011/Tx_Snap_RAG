# Tx_Snap_RAG  
**Production-Grade Retrieval-Augmented Generation (RAG) System for Texas SNAP (HHSC)**

## Overview

Tx_Snap_RAG is an end-to-end, production-oriented Retrieval-Augmented Generation (RAG) system built to ingest, process, and retrieve authoritative Texas SNAP (HHSC) policy and guidance content from public government websites.

The system is designed with a **data-first and incremental pipeline philosophy**, ensuring that changes in policy content are detected, processed, and reflected in downstream retrieval without reprocessing unchanged data.


## High-Level Architecture

config.yaml
│
▼
fetch.py        →  Web ingestion (HTML + PDFs, incremental)
│
▼
pages.py        →  Clean, normalize, and organize text
│
▼
chunk.py        →  Structure-aware chunking for retrieval
│
▼
(chunks.jsonl)  →  Ready for embeddings & vector indexing

`data_main.py` acts strictly as a **pipeline orchestrator**, calling each stage in sequence.  
All business logic lives inside individual pipeline modules.

---

## Design Principles

### Configuration-Driven
All system behavior is defined in `config.yaml`, including:
- crawl scope and safety rules
- chunking parameters
- embedding configuration
- retrieval and generation constraints

This allows system behavior to change without modifying code.

---

### Incremental & Idempotent Pipelines
Each stage avoids unnecessary recomputation:
- Fetch skips unchanged pages using HTTP metadata and hashes
- Organize skips already-processed documents
- Chunking only re-chunks documents whose text changed

This enables fast re-runs, lower cost, and safe continuous updates.

---

### Strong Data Contracts
Pydantic models define explicit schemas at each stage:
- `FetchRecord`
- `OrganizedDoc`
- `ChunkRecord`

This prevents silent data corruption and enforces predictable downstream behavior.

---

### Observability First
Every pipeline stage emits structured logs:
- stage start / completion
- processed vs skipped counts
- warnings for malformed or missing data

Logs are suitable for local debugging or cloud-based monitoring systems.

---

## Repository Structure
Tx_Snap_RAG/
├── data_main.py              # Pipeline orchestrator
├── config.yaml               # System configuration
│
├── src/
│   ├── core/
│   │   ├── logging.py        # Centralized logging
│   │   ├── settings.py       # YAML → Pydantic config loader
│   │   └── context.py        # run_id generation
│   │
│   └── ingest/
│       ├── fetch.py          # Web & PDF ingestion
│       ├── pages.py          # Cleaning & organization
│       └── chunk.py          # Chunking logic
│
├── data/
│   ├── raw/                  # Raw HTML & PDFs
│   ├── processed/            # Cleaned text files
│   ├── organized/            # docs.jsonl metadata index
│   └── chunks/               # chunks.jsonl for RAG
│
└── artifacts/
└── logs/                 # Pipeline logs

---

## Pipeline Stages

### 1. Fetch (Web Ingestion)

**Purpose:**  
Ingest authoritative SNAP policy content while avoiding unnecessary downloads.

**Key Features:**
- Domain and path allow/deny rules
- Incremental updates using HTTP metadata
- HTML and PDF handling
- Append-only fetch manifest for auditability

**Outputs:**
- `data/raw/*.html`
- `data/raw/pdfs/*.pdf`
- `data/raw/fetch_manifest.jsonl`

---

### 2. Pages (Clean & Organize)

**Purpose:**  
Convert raw web artifacts into clean, model-ready text while preserving provenance.

**Processing Includes:**
- Removal of navigation, headers, footers, and boilerplate
- Extraction of meaningful policy content
- Table-of-contents and empty page filtering
- PDF text extraction

**Outputs:**
- `data/processed/<doc_id>.txt`
- `data/organized/docs.jsonl`

Each organized record contains:
- document ID
- source URL
- document type (HTML / PDF)
- character counts
- file paths

---

### 3. Chunking (Retrieval Preparation)

**Purpose:**  
Prepare text chunks optimized for semantic retrieval.

**Chunking Strategy:**
- Paragraph-first chunking
- Sentence-based fallback for long sections
- Overlapping chunks to prevent boundary loss
- Stable, hash-based chunk IDs

**Outputs:**
- `data/chunks/chunks.jsonl`

Each chunk includes:
- `chunk_id`
- `doc_id` and source URL
- character offsets
- token estimates

---

## Running the Pipeline

Activate your virtual environment and run:

```bash
python data_main.py
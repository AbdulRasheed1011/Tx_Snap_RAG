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
   ├── langchain_rag.py # LangChain BM25 + optional FAISS hybrid + Ollama generation
   ├── retrieve.py      # Legacy hybrid retrieval (FAISS + BM25) + rerank + confidence gating
   ├── embed_index.py   # (Optional) Build FAISS index (requires OpenAI embeddings)
   └── main.py          # RAG CLI (LangChain + Ollama) + timing
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
├── config.yaml               # Declarative config
├── data_main.py              # Ingestion pipeline entrypoint
├── main.py                   # RAG CLI (retrieval + answer + timing)
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── docker/
│   ├── Dockerfile            # FastAPI image
│   └── compose.yaml          # Local container run
├── infra/
│   └── terraform/            # AWS ECS + ALB + Route53 + ACM
├── scripts/
│   ├── run_api.sh            # Local FastAPI run helper
│   └── aws_public_deploy.sh  # One-command AWS deploy helper
├── src/
│   ├── api/
│   │   ├── main.py           # FastAPI app
│   │   ├── metrics.py        # Prometheus metrics
│   │   ├── models.py         # Request/response schemas
│   │   ├── ollama_client.py  # Ollama HTTP client
│   │   └── settings.py       # API settings
│   ├── core/
│   │   ├── context.py
│   │   ├── logging.py
│   │   └── settings.py
│   ├── ingest/
│   │   ├── chunk.py
│   │   ├── fetch.py
│   │   └── pages.py
│   └── rag/
│       ├── embed_index.py
│       ├── langchain_rag.py
│       ├── query_index.py
│       ├── rag_answer.py
│       └── retrieve.py
├── tests/
│   └── test_api.py
├── docs/
│   └── PROBLEM_SUCCESS_SPEC.md
├── data/                     # generated artifacts
└── artifacts/                # generated artifacts
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

### 2) (Optional) Build FAISS index (legacy retriever path, requires OpenAI embeddings)

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

### 4) Run end-to-end RAG CLI (LangChain + Ollama)

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
- `OPENAI_API_KEY` (optional; enables LangChain FAISS hybrid when index artifacts exist)
- `RAG_DISABLE_GENERATION` (optional, set `true` for retrieval-only debugging)

Retrieval mode behavior:
- `retrieval.hybrid: true` + `OPENAI_API_KEY` + FAISS artifacts (`artifacts/index/*`) => `langchain_hybrid`
- otherwise => `langchain_bm25` (automatic safe fallback)

---

## Deploy (FastAPI + Docker)

### Local API (no Docker)

```bash
.venv/bin/python data_main.py
./scripts/run_api.sh
```

API endpoints:
- `GET /healthz`
- `GET /readyz`
- `GET /metrics` (Prometheus)
- `POST /answer` (RAG)

Example request:
```bash
curl -sS -X POST http://localhost:8000/answer \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is SNAP?"}' | python -m json.tool
```

### Docker

Assumption: Ollama runs on your host machine (macOS). The container reaches it via `host.docker.internal`.

```bash
docker compose -f docker/compose.yaml up --build
```

Smoke-test (without Ollama) by disabling generation:
```bash
RAG_DISABLE_GENERATION=true docker compose -f docker/compose.yaml up --build
```

---

## Deploy on AWS (Public API)

This repo includes an ECS Fargate deployment behind an ALB (HTTPS) using Terraform + ACM + Route53.

What you get:
- Public API endpoint via custom domain + TLS certificate
- Ollama runs as a sidecar container in the same ECS task
- Prometheus metrics endpoint (`/metrics`)
- API key auth via `X-API-Key` header (required)
- Startup safety: API readiness only turns green when the configured Ollama model is available

### Prereqs
- AWS account + credentials configured locally (`aws configure`)
- Terraform installed (>= 1.5)
- Docker running (Colima or Docker Desktop)
- Route53 hosted zone ID, VPC ID, and at least two subnet IDs in your target region

---

### Fastest path (recommended): one command deploy script

```bash
./scripts/aws_public_deploy.sh \
  --aws-region us-east-1 \
  --hosted-zone-name neweraon.com \
  --hosted-zone-id Z1234567890ABC \
  --api-subdomain api \
  --vpc-id vpc-0123456789abcdef0 \
  --subnet-ids subnet-aaa111,subnet-bbb222 \
  --image-tag latest \
  --desired-count 1 \
  --api-key-value 'REPLACE_WITH_STRONG_KEY'
```

What this script does:
1. Creates base AWS infra with service scaled to zero (no broken image pull).
2. Pushes your FastAPI image to ECR.
3. Scales ECS service up with HTTPS endpoint enabled.
4. Prints your public API URL and test commands.

---

### Manual path (Terraform + Docker)

#### 1) Create AWS resources (bootstrap)

```bash
cd infra/terraform
terraform init

terraform apply \
  -var 'aws_region=us-east-1' \
  -var 'hosted_zone_name=neweraon.com' \
  -var 'hosted_zone_id=Z1234567890ABC' \
  -var 'api_subdomain=api' \
  -var 'vpc_id=vpc-0123456789abcdef0' \
  -var 'subnet_ids=["subnet-aaa111","subnet-bbb222"]' \
  -var 'image_tag=bootstrap' \
  -var 'desired_count=0'
```

Terraform outputs:
- `ecr_repository_url`
- `alb_dns_name`
- `api_base_url`
- `api_key_secret_arn`

Set the API key (stored in Secrets Manager; not in Terraform state):
```bash
AWS_REGION=us-east-1
SECRET_ARN="$(cd infra/terraform && terraform output -raw api_key_secret_arn)"

aws secretsmanager put-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$SECRET_ARN" \
  --secret-string "REPLACE_WITH_STRONG_KEY"
```

#### 2) Build & push the API image to ECR

```bash
AWS_REGION=us-east-1
ECR_REPO_URL="$(cd infra/terraform && terraform output -raw ecr_repository_url)"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${ECR_REPO_URL%/*}"

docker build -f docker/Dockerfile -t "$ECR_REPO_URL:latest" .
docker push "$ECR_REPO_URL:latest"
```

#### 3) Re-apply Terraform (turn service on)

```bash
cd infra/terraform
terraform apply \
  -var 'aws_region=us-east-1' \
  -var 'hosted_zone_name=neweraon.com' \
  -var 'hosted_zone_id=Z1234567890ABC' \
  -var 'api_subdomain=api' \
  -var 'vpc_id=vpc-0123456789abcdef0' \
  -var 'subnet_ids=["subnet-aaa111","subnet-bbb222"]' \
  -var 'desired_count=1' \
  -var 'image_tag=latest'
```

#### 4) Call the public API

```bash
API_URL="$(cd infra/terraform && terraform output -raw api_base_url)"
curl -sS -X POST "$API_URL/answer" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: REPLACE_WITH_STRONG_KEY" \
  -d '{"question":"What is SNAP?"}' | python -m json.tool
```

Note: first startup can take longer while Ollama downloads the model. `/readyz` reports model status.

---

### Troubleshooting

1) `bash: aws/terraform/docker: command not found`
- Install missing tools and restart your shell.
- Verify with: `command -v aws terraform docker`

2) `bash: gsed: command not found`
- You likely have an alias/function in shell startup files.
- Check with: `type terraform` and `type aws`
- Temporary bypass: run commands with `command terraform ...` and `command aws ...`

3) Terraform `No valid credential sources found`
- Run `aws configure` and verify with `aws sts get-caller-identity`

4) IAM `UnauthorizedOperation` for `DescribeVpcs` or `ListHostedZones`
- Use explicit IDs (`hosted_zone_id`, `vpc_id`, `subnet_ids`) as shown above.
- If still blocked, ask your AWS admin for missing IAM permissions.

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

- Retrieval and grounding evaluation
- Monitoring and drift detection

---

## Intent

This repository demonstrates how to design and maintain **RAG systems with production discipline**, emphasizing data quality, reproducibility, and operational reliability over one-off experimentation.

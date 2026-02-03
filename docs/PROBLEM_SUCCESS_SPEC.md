# Problem & Success Spec (Tx_Snap_RAG)

## Objective
Provide accurate, grounded answers about Texas SNAP (HHSC) policies and user actions (eligibility basics, reporting changes, how to apply, timelines, what to submit) using *only* authoritative, ingested sources (HHSC + YourTexasBenefits) with citations.

## Primary Users
- Texas residents/applicants and benefits recipients who need clear guidance.
- Case workers/support staff who need quick retrieval of policy references.
- Internal developers/operators maintaining the RAG system.

## Non-Goals (v1)
- Legal advice; we provide informational guidance with citations.
- Personalized eligibility determinations beyond what the documents specify.
- Writing/filing applications on behalf of a user.

## Constraints
- Sources are restricted to allowlisted domains + paths in `config.yaml`.
- Answers must be grounded in retrieved content and cite supporting chunks.
- Privacy: user questions may contain sensitive info; do not store raw queries in logs by default.
- Local-first: support running without external keys (BM25-only), but optionally enhance with dense retrieval (FAISS + embeddings).

## Success Metrics
- Groundedness: % of answer sentences that have at least one supporting citation.
- Retrieval precision@k (manual eval set): how often top-k contains the correct supporting passage.
- Abstain quality: when evidence is weak, the system should refuse rather than hallucinate.
- Latency: p50 / p95 end-to-end time for `/answer`.
- Reliability: uptime of the API + error rate.

## Baseline
- BM25-only retrieval over `data/chunks/chunks.jsonl`.
- Ollama generation constrained to provided context + citations.

## Risks
- Irrelevant retrieval leads to hallucinations (mitigated by hybrid retrieval + rerank + gating).
- Source drift / outdated policy pages over time.
- Ingestion failures silently reducing corpus quality.
- Ollama availability/resources on host system.

## Acceptance Criteria (v1)
- API returns an answer with citations or abstains with a clear reason.
- `/metrics` exposes request counts and latency.
- `/readyz` reflects configured retrieval mode and data paths.
- Docker deployment works locally (API container + external Ollama).


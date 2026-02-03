# Failure Mode Remediation Report

Date: 2026-02-03

## Scope
This report covers architecture-level fixes for the public FastAPI + LangChain RAG system running on AWS ECS Fargate with an ALB and Ollama sidecar.

## 1) Startup/Readiness Deadlocks
- **Failure mode**: Service starts but cannot serve safely (missing API key, unsafe CORS wildcard, missing runtime dependencies).
- **Fix implemented**:
  - Enforced startup validation for required API key and wildcard CORS blocking by default.
  - Exposed security/runtime state in `/readyz`.
  - Added secure deploy defaults in Terraform and deploy script.
- **Code changes**:
  - `src/api/settings.py`
  - `src/api/main.py`
  - `infra/terraform/variables.tf`
  - `infra/terraform/main.tf`
  - `scripts/aws_public_deploy.sh`
- **How to verify**:
  1. Start API without `API_KEY` and `REQUIRE_API_KEY=true` -> startup should fail with clear error in `/readyz`.
  2. Set `CORS_ALLOW_ORIGINS=*` without `ALLOW_INSECURE_CORS_WILDCARD=true` -> startup should fail.

## 2) Capacity Saturation / Tail Latency
- **Failure mode**: Large inference requests overwhelm a single task and create high latency/timeout cascades.
- **Fix implemented**:
  - Added in-process concurrency guard for `/answer` returning `429` when saturated.
  - Added ECS autoscaling target tracking (CPU + memory).
  - Added CloudWatch alarm for ALB target 5xx spikes.
- **Code changes**:
  - `src/api/main.py`
  - `infra/terraform/variables.tf`
  - `infra/terraform/main.tf`
- **How to verify**:
  1. Set `MAX_CONCURRENT_REQUESTS=1` and send parallel requests -> excess requests should return `429`.
  2. Confirm Terraform creates `aws_appautoscaling_*` resources and `aws_cloudwatch_metric_alarm.alb_target_5xx`.

## 3) Retrieval Quality Drift / Stale Index
- **Failure mode**: FAISS metadata/chunk drift degrades retrieval quality silently.
- **Fix implemented**:
  - Added FAISS-to-chunk overlap validation before enabling hybrid retrieval.
  - If overlap is below threshold, hybrid retrieval is disabled with explicit reason.
- **Code changes**:
  - `src/rag/langchain_rag.py`
  - `infra/terraform/variables.tf` (`rag_min_faiss_chunk_overlap`)
  - `infra/terraform/main.tf` (env wiring)
- **How to verify**:
  1. Build mismatched chunks/index and start API.
  2. Check `/readyz` and `/answer.retrieval.reason` for drift/fallback reason.

## 4) Dependency Outages (Ollama/LLM call failures)
- **Failure mode**: Transient generation failures cause request failures or unstable behavior.
- **Fix implemented**:
  - Added generation retry loop with backoff.
  - Added graceful fallback answer when generation remains unavailable after retries.
- **Code changes**:
  - `src/rag/langchain_rag.py`
  - `infra/terraform/variables.tf`
  - `infra/terraform/main.tf`
- **How to verify**:
  1. Stop Ollama during requests.
  2. Confirm response returns controlled fallback message with reason containing `generation_unavailable` instead of hard failure.

## 5) Public API Security Misconfiguration
- **Failure mode**: Public endpoint accidentally exposed without auth or with permissive CORS.
- **Fix implemented**:
  - API key requirement is enabled by default.
  - Wildcard CORS blocked by default unless explicitly opted in.
  - Deployment script now requires `--api-key-value`.
- **Code changes**:
  - `src/api/settings.py`
  - `src/api/main.py`
  - `scripts/aws_public_deploy.sh`
  - `infra/terraform/terraform.tfvars.example`
- **How to verify**:
  1. Deploy without API key -> blocked by deploy script.
  2. Call `/answer` without `X-API-Key` -> `401`.

## Operational Notes
- Local developer flow remains simple: `scripts/run_api.sh` defaults to `REQUIRE_API_KEY=false`.
- Production flow remains secure: Terraform/deploy script keep `require_api_key=true`.

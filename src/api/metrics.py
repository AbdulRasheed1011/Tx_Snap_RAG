from __future__ import annotations

from prometheus_client import Counter, Histogram


REQUESTS_TOTAL = Counter(
    "tx_snap_rag_requests_total",
    "Total API requests.",
    ["endpoint", "status"],
)

ANSWER_ATTEMPTS_TOTAL = Counter(
    "tx_snap_rag_answer_attempts_total",
    "Total answer attempts.",
    ["retrieval_mode", "should_answer"],
)

REQUEST_LATENCY_SECONDS = Histogram(
    "tx_snap_rag_request_latency_seconds",
    "Request latency seconds.",
    ["endpoint"],
)


from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(__import__("json").dumps(r) + "\n")


def test_healthz() -> None:
    from src.api.main import app

    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_answer_generation_disabled(tmp_path: Path, monkeypatch) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "doc_id": "doc1",
                "chunk_id": "c1",
                "url": "https://example.com/doc1",
                "kind": "html",
                "text": "SNAP helps people buy food.",
                "start_char": 0,
                "end_char": 27,
                "token_estimate": 7,
                "created_at": "2026-02-03T00:00:00Z",
            },
            {
                "doc_id": "doc2",
                "chunk_id": "c2",
                "url": "https://example.com/doc2",
                "kind": "html",
                "text": "Applications can be submitted online.",
                "start_char": 0,
                "end_char": 36,
                "token_estimate": 8,
                "created_at": "2026-02-03T00:00:00Z",
            },
        ],
    )

    monkeypatch.setenv("RAG_DISABLE_GENERATION", "true")
    monkeypatch.setenv("RAG_CHUNKS_PATH", str(chunks_path))
    monkeypatch.setenv("RAG_META_PATH", str(tmp_path / "meta.jsonl"))
    monkeypatch.setenv("RAG_INDEX_PATH", str(tmp_path / "index.faiss"))
    monkeypatch.setenv("RAG_CONFIG_PATH", "config.yaml")

    # Re-import app after env is set so startup picks up temp paths.
    if "src.api.main" in list(__import__("sys").modules.keys()):
        __import__("importlib").reload(__import__("sys").modules["src.api.main"])

    from src.api.main import app

    client = TestClient(app)
    r = client.post("/answer", json={"question": "What is SNAP?"})
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert body["answer"] == "(generation disabled)"
    assert len(body["citations"]) >= 1


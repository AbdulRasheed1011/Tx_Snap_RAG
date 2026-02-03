from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List

import requests

from src.core.settings import AppConfig
from src.rag.retrieve import Hit, Retriever


@dataclass(frozen=True)
class RAGResult:
    answer: str
    citations: List[Dict[str, Any]]
    contexts: List[Hit]


def format_context(hits: List[Hit], max_chars_per_chunk: int = 1200) -> str:
    blocks: List[str] = []
    for i, hit in enumerate(hits, start=1):
        md = hit.metadata or {}
        doc_id = md.get("doc_id", "unknown_doc")
        span = f"{md.get('start_char', 0)}-{md.get('end_char', 0)}"
        url = md.get("url", "")

        chunk_text = (hit.text or "").strip().replace("\n", " ")
        if len(chunk_text) > max_chars_per_chunk:
            chunk_text = chunk_text[:max_chars_per_chunk].rstrip() + " ..."

        blocks.append(f"[{i}] doc_id={doc_id} span={span} url={url}\n{chunk_text}\n")

    return "\n".join(blocks)


def build_prompt(question: str, context_block: str) -> str:
    return textwrap.dedent(
        f"""
        You are a careful assistant answering questions using ONLY the provided context.
        If the context does not contain the answer, say: "I don't have enough information in the provided documents."

        Rules:
        - Use only the context below.
        - Cite sources using bracket numbers like [1], [2] after the sentence they support.
        - Be concise and factual.

        Question:
        {question}

        Context:
        {context_block}

        Answer:
        """
    ).strip()


def call_ollama(
    prompt: str,
    *,
    model: str = "llama3.1",
    url: str = "http://localhost:11434/api/generate",
) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False}
    response = requests.post(url, json=payload, timeout=180)
    response.raise_for_status()
    data = response.json()
    return (data.get("response") or "").strip()


def rag_answer(
    question: str,
    *,
    top_k: int | None = None,
    llm_provider: str = "ollama",
) -> RAGResult:
    cfg = AppConfig.load("config.yaml")
    retriever = Retriever()

    retrieval = retriever.retrieve_with_result(
        query=question,
        top_k=top_k or cfg.retrieval.top_k,
        min_score=cfg.retrieval.min_score,
    )
    hits = retrieval.hits

    if not hits or not retrieval.should_answer:
        return RAGResult(
            answer="I don't have enough information in the provided documents.",
            citations=[],
            contexts=[],
        )

    context_block = format_context(hits)
    prompt = build_prompt(question, context_block)

    if llm_provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "llama3.1")
        answer = call_ollama(prompt, model=model)
    else:
        raise ValueError(f"Unsupported llm_provider: {llm_provider}")

    citations: List[Dict[str, Any]] = []
    for i, hit in enumerate(hits, start=1):
        md = hit.metadata or {}
        citations.append(
            {
                "cite": f"[{i}]",
                "score": hit.score,
                "chunk_id": hit.id,
                "doc_id": md.get("doc_id"),
                "url": md.get("url"),
                "start_char": md.get("start_char"),
                "end_char": md.get("end_char"),
            }
        )

    return RAGResult(answer=answer, citations=citations, contexts=hits)


def main() -> None:
    print("RAG Answer CLI (type 'exit' to quit)\n")
    while True:
        question = input("question> ").strip()
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break

        result = rag_answer(question, llm_provider="ollama")
        print("\nANSWER:\n")
        print(result.answer)

        print("\nCITATIONS:")
        for c in result.citations:
            print(
                f"{c['cite']} score={c['score']:.4f} doc_id={c['doc_id']} "
                f"range={c['start_char']}-{c['end_char']} url={c['url']}"
            )
        print("\n" + "-" * 72 + "\n")


if __name__ == "__main__":
    main()

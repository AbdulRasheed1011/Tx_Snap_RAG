from __future__ import annotations
import os
import textwrap
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import requests
from src.rag.retrieve import Retriever, Hit

@dataclass(frozen=True)
class RAGResult:
    answer: str
    citations: List[Dict[str, Any]]
    contexts: List[Hit]


def format_context(hits: List[Hit], max_chars_per_chunk: int = 1200) -> str:

    blocks = []
    for i, h in enumerate(hits, start=1):
        md = h.metadata or {}
        source_file = md.get("source_file", "unknown_source")
        section = md.get("section", "unknown_section")

        chunk_text = (h.text or "").strip().replace("\n", " ")
        if len(chunk_text) > max_chars_per_chunk:
            chunk_text = chunk_text[:max_chars_per_chunk].rstrip() + " ..."

        blocks.append(
            f"[{i}] source_file={source_file} section={section}\n"
            f"{chunk_text}\n"
        )
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


def call_ollama(prompt: str, model: str = "llama3.1", url: str = "http://localhost:11434/api/generate") -> str:

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    r = requests.post(url, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return (data.get("response") or "").strip()


def rag_answer(
    question: str,
    top_k: int = 5,
    llm_provider: str = "ollama",
) -> RAGResult:
    retriever = Retriever()
    hits = retriever.retrieve(question, top_k=top_k)

    context_block = format_context(hits)
    prompt = build_prompt(question, context_block)

    if llm_provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "llama3.1")
        answer = call_ollama(prompt, model=model)
    else:
        raise ValueError(f"Unsupported llm_provider: {llm_provider}")

    citations = []
    for i, h in enumerate(hits, start=1):
        md = h.metadata or {}
        citations.append(
            {
                "cite": f"[{i}]",
                "score": h.score,
                "source_file": md.get("source_file"),
                "section": md.get("section"),
                "chunk_file": md.get("chunk_file"),
                "id": h.id,
            }
        )

    return RAGResult(answer=answer, citations=citations, contexts=hits)


def main() -> None:
    print("RAG Answer CLI (type 'exit' to quit)\n")
    while True:
        q = input("question> ").strip()
        if not q:
            continue
        if q.lower() in {"exit", "quit"}:
            break

        result = rag_answer(q, top_k=5, llm_provider="ollama")
        print("\nANSWER:\n")
        print(result.answer)

        print("\nCITATIONS:")
        for c in result.citations:
            print(f"{c['cite']} score={c['score']:.4f} source_file={c['source_file']} section={c['section']}")
        print("\n" + "-" * 60 + "\n")


if __name__ == "__main__":
    main()
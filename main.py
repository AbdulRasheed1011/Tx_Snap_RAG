from __future__ import annotations

import os
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import requests
from openai import OpenAI

from src.core.settings import AppConfig
from src.rag.retrieve import RetrievalResult, Retriever


@dataclass(frozen=True)
class RetrievedChunk:
    cite: str
    score: float
    chunk_id: str
    text: str
    metadata: Dict[str, Any]

def _format_context(hits: List[RetrievedChunk], max_chars_per_chunk: int = 1200) -> str:
    blocks: List[str] = []
    for h in hits:
        md = h.metadata or {}
        doc_id = md.get("doc_id", "unknown_doc")
        span = f"{md.get('start_char', 0)}-{md.get('end_char', 0)}"
        url = md.get("url", "")
        chunk_text = h.text.strip().replace("\n", " ")
        if len(chunk_text) > max_chars_per_chunk:
            chunk_text = chunk_text[:max_chars_per_chunk].rstrip() + " ..."
        blocks.append(f"{h.cite} doc_id={doc_id} span={span} url={url}\n{chunk_text}\n")
    return "\n".join(blocks)


def _build_prompt(question: str, context_block: str) -> str:
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


def _call_ollama(prompt: str) -> str:
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    payload = {"model": model, "prompt": prompt, "stream": False}
    response = requests.post(url, json=payload, timeout=180)
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def _call_openai(prompt: str, cfg: AppConfig) -> str:
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        temperature=cfg.generation.temperature,
        max_tokens=cfg.generation.max_tokens,
        messages=[
            {"role": "system", "content": "Answer only from provided context and include citations."},
            {"role": "user", "content": prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def _retrieve_chunks(
    query: str, cfg: AppConfig
) -> tuple[List[RetrievedChunk], str, bool, str]:
    try:
        retriever = Retriever()
        result: RetrievalResult = retriever.retrieve_with_result(
            query=query,
            top_k=cfg.retrieval.top_k,
            min_score=cfg.retrieval.min_score,
        )
        out = [
            RetrievedChunk(
                cite=f"[{i}]",
                score=h.score,
                chunk_id=h.id,
                text=h.text,
                metadata=h.metadata or {},
            )
            for i, h in enumerate(result.hits, start=1)
        ]
        return out, result.mode, result.should_answer, result.reason
    except Exception as e:
        return [], "none", False, f"retriever_error: {e}"


def _generate_answer(prompt: str, cfg: AppConfig) -> tuple[str, str]:
    try:
        return _call_ollama(prompt), "ollama"
    except Exception as ollama_error:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "Ollama generation failed and OPENAI_API_KEY is not set. "
                "Start Ollama (`ollama serve`) or configure OPENAI_API_KEY."
            ) from ollama_error
        return _call_openai(prompt, cfg), "openai"


def main() -> None:
    cfg = AppConfig.load("config.yaml")
    print("RAG CLI (tries Ollama first, then OpenAI fallback). Type 'exit' to quit.\n")

    while True:
        question = input("question> ").strip()
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break

        t0 = time.perf_counter()

        t_retrieve0 = time.perf_counter()
        hits, retrieval_mode, should_answer, retrieval_reason = _retrieve_chunks(question, cfg)
        retrieve_sec = time.perf_counter() - t_retrieve0

        if not hits or not should_answer:
            total_sec = time.perf_counter() - t0
            print("\nI don't have enough information in the provided documents.")
            print(f"retrieval_reason: {retrieval_reason}")
            print(f"timing: retrieval={retrieve_sec:.3f}s generation=0.000s total={total_sec:.3f}s")
            print("-" * 72)
            continue

        context = _format_context(hits)
        prompt = _build_prompt(question, context)

        t_gen0 = time.perf_counter()
        try:
            answer, generator_mode = _generate_answer(prompt, cfg)
        except Exception as e:
            total_sec = time.perf_counter() - t0
            print(f"\nGeneration failed: {e}")
            print(f"mode: retrieval={retrieval_mode}, generation=failed")
            print(f"timing: retrieval={retrieve_sec:.3f}s generation=0.000s total={total_sec:.3f}s")
            print("-" * 72)
            continue
        gen_sec = time.perf_counter() - t_gen0
        total_sec = time.perf_counter() - t0

        print("\nANSWER:\n")
        print(answer)
        print("\nCITATIONS:")
        for h in hits:
            md = h.metadata or {}
            print(
                f"{h.cite} score={h.score:.4f} doc_id={md.get('doc_id')} "
                f"range={md.get('start_char')}-{md.get('end_char')} url={md.get('url')}"
            )

        print(
            f"\nmode: retrieval={retrieval_mode}, generation={generator_mode}\n"
            f"timing: retrieval={retrieve_sec:.3f}s generation={gen_sec:.3f}s total={total_sec:.3f}s"
        )
        print("-" * 72)


if __name__ == "__main__":
    main()

from __future__ import annotations

import os

from src.rag.langchain_rag import LangChainRAG


def main() -> None:
    print("RAG CLI (LangChain + Ollama). Type 'exit' to quit.\n")

    engine = LangChainRAG(
        config_path=os.getenv("RAG_CONFIG_PATH", "config.yaml"),
        chunks_path=os.getenv("RAG_CHUNKS_PATH", "data/chunks/chunks.jsonl"),
        index_path=os.getenv("RAG_INDEX_PATH", "artifacts/index/index.faiss"),
        meta_path=os.getenv("RAG_META_PATH", "artifacts/index/meta.jsonl"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        disable_generation=os.getenv("RAG_DISABLE_GENERATION", "false").lower() in {"1", "true", "yes"},
    )

    while True:
        question = input("question> ").strip()
        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            break

        result = engine.answer(question)

        print("\nANSWER:\n")
        print(result.answer)
        print("\nCITATIONS:")
        if not result.citations:
            print("(none)")
        else:
            for c in result.citations:
                md = c.metadata or {}
                print(
                    f"{c.cite} score={c.score:.4f} doc_id={md.get('doc_id')} "
                    f"range={md.get('start_char')}-{md.get('end_char')} url={md.get('url')}"
                )

        print(
            f"\nmode: {result.mode} | should_answer: {result.should_answer} | reason: {result.reason}\n"
            f"timing: retrieval={result.retrieval_seconds:.3f}s "
            f"generation={result.generation_seconds:.3f}s "
            f"total={result.total_seconds:.3f}s"
        )
        print("-" * 72)


if __name__ == "__main__":
    main()

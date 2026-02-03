from __future__ import annotations

from src.core.settings import AppConfig
from src.rag.retrieve import Retriever


def main() -> None:
    cfg = AppConfig.load("config.yaml")
    retriever = Retriever()

    print("\nFAISS Query CLI (type 'exit' to quit)\n")
    while True:
        query = input("query> ").strip()
        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            break

        result = retriever.retrieve_with_result(
            query=query,
            top_k=cfg.retrieval.top_k,
            min_score=cfg.retrieval.min_score,
        )
        hits = result.hits

        if not hits:
            print("\nNo matches above the configured threshold.\n")
            continue

        print(f"\nmode={result.mode} should_answer={result.should_answer} reason={result.reason}\n")
        print("\nTop matches:\n")
        for i, hit in enumerate(hits, start=1):
            md = hit.metadata or {}
            snippet = hit.text.replace("\n", " ").strip()[:280]
            print(
                f"#{i} score={hit.score:.4f} dense={hit.dense_score:.4f} "
                f"bm25={hit.bm25_score:.4f} cov={hit.coverage:.2f} row={hit.row} id={hit.id}"
            )
            print(f"   doc_id={md.get('doc_id')} kind={md.get('kind')}")
            print(f"   range={md.get('start_char')}-{md.get('end_char')} url={md.get('url')}")
            print(f"   text: {snippet}...")
            print("")

        print("-" * 72)


if __name__ == "__main__":
    main()

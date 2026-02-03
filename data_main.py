from __future__ import annotations

from src.core.context import get_run_id
from src.core.logging import get_logger
from src.core.settings import AppConfig

from src.ingest.fetch import fetch_seed_urls
import src.ingest.pages as pages
import src.ingest.chunk as chunk

logger = get_logger("data_main")


def main() -> None:
    """
    Pipeline entrypoint.

    Responsibility of this file:
    - Load config
    - Create run_id
    - Call pipeline stages in order

    Business logic lives inside:
    - fetch.py
    - pages.py
    - chunk.py
    """

    run_id = get_run_id()
    cfg = AppConfig.load("config.yaml")

    logger.info(
        f"run_id={run_id} stage=start "
        f"project={cfg.project.name} seed_urls={len(cfg.sources.seed_urls)}"
    )

    # -------- Stage 1: Fetch --------
    fetch_summary = fetch_seed_urls(
        cfg=cfg,
        out_raw_dir="data/raw",
        run_id=run_id,
    )
    logger.info(f"run_id={run_id} stage=fetch_done summary={fetch_summary}")

    # -------- Stage 2: Organize / Clean --------
    organizer = getattr(pages, "organize_all", None) or getattr(pages, "clean_all")
    organize_summary = organizer(
        raw_dir="data/raw",
        processed_dir="data/processed",
        organized_dir="data/organized",
    )
    logger.info(f"run_id={run_id} stage=organize_done summary={organize_summary}")

    # -------- Stage 3: Chunk --------
    chunker = getattr(chunk, "chunk_all", None)
    if chunker is None:
        raise ImportError(f"chunk_all not found in {getattr(chunk, '__file__', None)}")

    chunk_summary = chunker(
        organized_index="data/organized/docs.jsonl",
        processed_dir="data/processed",
        out_dir="data/chunks",
    )
    logger.info(f"run_id={run_id} stage=chunk_done summary={chunk_summary}")

    logger.info(f"run_id={run_id} stage=done")


if __name__ == "__main__":
    main()
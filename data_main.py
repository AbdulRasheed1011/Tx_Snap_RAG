from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.context import get_run_id
from src.core.logging import get_logger
from src.core.settings import AppConfig

from src.ingest.chunk import chunk_all
from src.ingest.fetch import fetch_seed_urls
from src.ingest.pages import organize_all

logger = get_logger("data_main")

CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class PipelinePaths:
    raw_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")
    organized_dir: Path = Path("data/organized")
    chunks_dir: Path = Path("data/chunks")


def _chunking_params(cfg: AppConfig) -> dict[str, int]:
    max_chars = cfg.chunking.max_tokens * CHARS_PER_TOKEN
    overlap_chars = cfg.chunking.overlap_tokens * CHARS_PER_TOKEN
    min_chunk_chars = cfg.chunking.min_tokens * CHARS_PER_TOKEN

    if min_chunk_chars > max_chars:
        raise ValueError(
            "Invalid chunking config: min_tokens must be <= max_tokens "
            f"(got {cfg.chunking.min_tokens} > {cfg.chunking.max_tokens})"
        )

    return {
        "max_chars": max_chars,
        "overlap_chars": overlap_chars,
        "min_chunk_chars": min_chunk_chars,
    }


def run_pipeline(cfg: AppConfig, run_id: str, paths: PipelinePaths) -> None:
    chunking = _chunking_params(cfg)

    logger.info(
        f"run_id={run_id} stage=start project={cfg.project.name} "
        f"seed_urls={len(cfg.sources.seed_urls)} chunk_method={cfg.chunking.method}"
    )

    fetch_summary = fetch_seed_urls(
        cfg=cfg,
        out_raw_dir=paths.raw_dir,
        run_id=run_id,
    )
    logger.info(f"run_id={run_id} stage=fetch_done summary={fetch_summary}")

    organize_summary = organize_all(
        raw_dir=paths.raw_dir,
        processed_dir=paths.processed_dir,
        organized_dir=paths.organized_dir,
    )
    logger.info(f"run_id={run_id} stage=organize_done summary={organize_summary}")

    chunk_summary = chunk_all(
        organized_index=paths.organized_dir / "docs.jsonl",
        processed_dir=paths.processed_dir,
        out_dir=paths.chunks_dir,
        max_chars=chunking["max_chars"],
        overlap_chars=chunking["overlap_chars"],
        min_chunk_chars=chunking["min_chunk_chars"],
    )
    logger.info(f"run_id={run_id} stage=chunk_done summary={chunk_summary}")

    logger.info(f"run_id={run_id} stage=done")


def main() -> None:
    run_id = get_run_id()
    cfg = AppConfig.load("config.yaml")
    paths = PipelinePaths()

    run_pipeline(cfg=cfg, run_id=run_id, paths=paths)


if __name__ == "__main__":
    main()

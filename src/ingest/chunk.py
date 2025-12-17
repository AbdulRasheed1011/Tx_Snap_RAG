import json
import re
from pathlib import Path

SECTION_PATTERN = re.compile(
    r"^(?:"
    r"[A-Z]-\d{3,4}\s*[,\-]?\s+.+|"
    r"Part\s+[A-Z],\s+.+|"
    r"Section\s+\d{3,4},\s+.+"
    r")$",
    re.IGNORECASE,
)


def chunk_handbook_text(text: str, source_file: str) -> list[dict]:
    """Split handbook-like text into chunks by section headers."""
    chunks: list[dict] = []
    current_section: str | None = None
    buffer: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if SECTION_PATTERN.match(line):
            if current_section and buffer:
                chunks.append(
                    {
                        "source_file": source_file,
                        "section": current_section,
                        "text": "\n".join(buffer).strip(),
                    }
                )
                buffer = []

            current_section = line
            continue

        buffer.append(line)

    if current_section and buffer:
        chunks.append(
            {
                "source_file": source_file,
                "section": current_section,
                "text": "\n".join(buffer).strip(),
            }
        )

    if not chunks and buffer:
        chunks.append(
            {
                "source_file": source_file,
                "section": "FULL_DOCUMENT",
                "text": "\n".join(buffer).strip(),
            }
        )

    return chunks

def chunk_one_file(input_txt: str | Path) -> list[dict]:
    input_txt = Path(input_txt)
    if not input_txt.exists():
        raise FileNotFoundError(f"Input file not found: {input_txt}")

    text = input_txt.read_text(encoding="utf-8", errors="ignore")
    return chunk_handbook_text(text, source_file=input_txt.name)


def save_chunks_jsonl(chunks: list[dict], out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")


if __name__ == "__main__":

    input_dir = Path("data/preprocessed")
    if not input_dir.exists():
        input_dir = Path("data/processed")

    output_dir = Path("data/organize")
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in: {input_dir}")

    all_chunks: list[dict] = []

    for txt_path in txt_files:
        chunks = chunk_one_file(txt_path)
        if not chunks:
            print(f"WARNING: 0 chunks produced for {txt_path.name}. Check SECTION_PATTERN / input text.")

        all_chunks.extend(chunks)

        per_file_out = output_dir / f"{txt_path.stem}.chunks.jsonl"
        save_chunks_jsonl(chunks, per_file_out)
        print(f"Saved {len(chunks)} chunks -> {per_file_out}")

    combined_out = output_dir / "chunks_all.jsonl"
    save_chunks_jsonl(all_chunks, combined_out)

    print("\nSummary:")
    print(f"  input_dir: {input_dir}")
    print(f"  files: {len(txt_files)}")
    print(f"  total_chunks: {len(all_chunks)}")
    print(f"  output_dir: {output_dir}")
    print(f"  combined: {combined_out}")
"""
_inspect_chunks.py
==================

Quick sanity-check utility: load chunks.jsonl and print a few random chunks
so you can eyeball chunk size, content quality, and metadata.

Run:
    python _inspect_chunks.py                 # 5 random chunks from chunks.jsonl
    python _inspect_chunks.py -n 10           # 10 random chunks
    python _inspect_chunks.py -f other.jsonl  # inspect a different file
    python _inspect_chunks.py --seed 42       # reproducible sample
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def load_chunks(path: Path) -> list[dict]:
    """Load a JSONL file into a list of chunk dicts."""
    if not path.exists():
        sys.exit(f"File not found: {path}. Run ingest_and_chunk.py first.")
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def print_chunk(chunk: dict, position: int, total: int) -> None:
    """Pretty-print a single chunk with its metadata."""
    print(f"===== CHUNK {position}/{total} =====")
    print(f"chunk_id : {chunk.get('chunk_id', '?')}")
    print(f"source   : {chunk.get('source', '?')}  ({chunk.get('doc_type', '?')})")
    if chunk.get("url"):
        print(f"url      : {chunk['url']}")
    print(f"index    : {chunk.get('chunk_index', '?')} of {chunk.get('num_chunks', '?')}  "
          f"|  {chunk.get('token_count', '?')} tokens, {chunk.get('char_count', '?')} chars")
    print("-- text --")
    print(chunk.get("text", ""))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print random chunks from a JSONL file for inspection.")
    parser.add_argument("-f", "--file", default="chunks.jsonl", help="JSONL file to inspect (default: chunks.jsonl).")
    parser.add_argument("-n", "--num", type=int, default=5, help="How many random chunks to print (default: 5).")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for a reproducible sample.")
    args = parser.parse_args()

    chunks = load_chunks(Path(args.file))
    if not chunks:
        sys.exit("No chunks found in file.")

    if args.seed is not None:
        random.seed(args.seed)

    sample_size = min(args.num, len(chunks))
    sample = random.sample(chunks, sample_size)

    print(f"Loaded {len(chunks)} chunks from {args.file}. Showing {sample_size} at random.\n")
    for i, chunk in enumerate(sample, 1):
        print_chunk(chunk, i, sample_size)


if __name__ == "__main__":
    main()

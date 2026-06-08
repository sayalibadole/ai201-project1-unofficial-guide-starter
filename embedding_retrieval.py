"""
embedding_retrieval.py
======================

Milestone 4 of "The Unofficial Guide" RAG system: **embedding + retrieval**.

Pipeline position:
    Ingestion -> Cleaning -> Chunking -> [EMBEDDING + VECTOR DB + RETRIEVAL] -> LLM Generation

What this script does
---------------------
1. Loads ``chunks.jsonl`` (produced by ingest_and_chunk.py).
2. Embeds each chunk's text with ``sentence-transformers/all-MiniLM-L6-v2``.
3. Stores each chunk in a **persistent** ChromaDB collection together with its
   text and metadata (source, doc_type, chunk_index, and any other fields).
4. Exposes ``retrieve(query, k=5)`` for top-k cosine-similarity search.

Cosine similarity is enforced by creating the collection with
``{"hnsw:space": "cosine"}`` and L2-normalizing all embeddings.

Run:
    python embedding_retrieval.py                 # build index (if empty) + sample query
    python embedding_retrieval.py --rebuild       # wipe + re-embed everything
    python embedding_retrieval.py --query "Which professor teaches CS 410?" -k 5

Dependencies:  pip install sentence-transformers chromadb
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = "all-MiniLM-L6-v2"   # short alias for sentence-transformers/all-MiniLM-L6-v2
CHUNKS_FILE = Path("chunks.jsonl")
PERSIST_DIR = Path("chroma_db")          # on-disk ChromaDB storage (not in-memory)
COLLECTION_NAME = "uiuc_mcs_reviews"

# Metadata fields we never want to store as Chroma metadata (the text is stored
# as the document itself; embedding is stored as the vector).
_NON_METADATA_KEYS = {"text", "embedding"}

# Lazily-loaded singletons so importing this module is cheap.
_MODEL: SentenceTransformer | None = None
_CLIENT: "chromadb.api.ClientAPI | None" = None


# ---------------------------------------------------------------------------
# Model / client / collection helpers
# ---------------------------------------------------------------------------
def get_model() -> SentenceTransformer:
    """Load (once) and return the all-MiniLM-L6-v2 embedding model."""
    global _MODEL
    if _MODEL is None:
        print(f"Loading embedding model: {MODEL_NAME} ...")
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


def get_client() -> "chromadb.api.ClientAPI":
    """Return a persistent ChromaDB client backed by PERSIST_DIR on disk."""
    global _CLIENT
    if _CLIENT is None:
        PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        _CLIENT = chromadb.PersistentClient(path=str(PERSIST_DIR))
    return _CLIENT


def get_collection():
    """Get (or create) the reviews collection configured for cosine similarity.

    ``hnsw:space = cosine`` tells Chroma's index to rank by cosine distance, so
    the closest results are the most semantically similar reviews.
    """
    client = get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts with all-MiniLM-L6-v2 (L2-normalized for cosine)."""
    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,        # unit vectors -> proper cosine geometry
        show_progress_bar=len(texts) > 1,
        convert_to_numpy=True,
    )
    return vectors.tolist()


# ---------------------------------------------------------------------------
# Chunk loading + metadata
# ---------------------------------------------------------------------------
def load_chunks(path: Path) -> list[dict]:
    """Load chunk dictionaries from a JSONL file."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run ingest_and_chunk.py first to produce chunks."
        )
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def chunk_metadata(chunk: dict) -> dict:
    """Build a Chroma-safe metadata dict from a chunk.

    Keeps every field except the raw text/embedding, so source, doc_type,
    chunk_index, url, source_path, etc. are all preserved. Chroma only accepts
    str/int/float/bool values, so None becomes "" and other types are stringified.
    """
    meta: dict = {}
    for key, value in chunk.items():
        if key in _NON_METADATA_KEYS:
            continue
        if value is None:
            meta[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            meta[key] = value
        else:
            meta[key] = json.dumps(value, ensure_ascii=False)
    return meta


def chunk_id(chunk: dict, index: int, seen: set[str]) -> str:
    """Return a stable, unique id for a chunk.

    Prefers the ingestion-provided ``chunk_id``; otherwise composes one from
    source + chunk_index. Appends a suffix if a collision is detected so no
    chunk is silently overwritten.
    """
    base = str(chunk.get("chunk_id")
               or f"{chunk.get('source', 'doc')}::{chunk.get('chunk_index', index)}")
    candidate = base
    suffix = 1
    while candidate in seen:
        candidate = f"{base}#{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# Index building (embedding pipeline + storage)
# ---------------------------------------------------------------------------
def build_index(rebuild: bool = False) -> int:
    """Embed every chunk in CHUNKS_FILE and store it in ChromaDB.

    ``rebuild=True`` drops the existing collection first so the index is rebuilt
    from scratch. Otherwise chunks are ``upsert``-ed by id, which makes re-runs
    idempotent (no duplicates, metadata refreshed) rather than appending copies.
    Returns the number of chunks stored.
    """
    if rebuild:
        try:
            get_client().delete_collection(COLLECTION_NAME)
            print(f"Deleted existing collection '{COLLECTION_NAME}'.")
        except Exception:
            pass  # collection didn't exist yet

    collection = get_collection()
    chunks = load_chunks(CHUNKS_FILE)
    if not chunks:
        print("No chunks to index.")
        return 0

    texts = [c["text"] for c in chunks]
    metadatas = [chunk_metadata(c) for c in chunks]
    seen: set[str] = set()
    ids = [chunk_id(c, i, seen) for i, c in enumerate(chunks)]

    print(f"Embedding {len(texts)} chunks with {MODEL_NAME} ...")
    embeddings = embed_texts(texts)

    # Upsert in batches (Chroma has a per-call ceiling; batching is also gentler
    # on memory for large corpora).
    batch = 256
    for start in range(0, len(ids), batch):
        end = start + batch
        collection.upsert(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=texts[start:end],
            metadatas=metadatas[start:end],
        )

    print(f"Stored {collection.count()} chunks in ChromaDB at '{PERSIST_DIR}'.")
    return collection.count()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
# Matches course codes like "CS 425", "CS425", "STAT 420", "ECE 314".
_COURSE_RE = re.compile(r"\b([A-Za-z]{2,4})\s*-?\s*(\d{3})\b")

# Score bonuses blended on top of cosine similarity. Kept modest so they only
# reshuffle near-ties -- a clearly more similar chunk still wins outright.
COURSE_BONUS = 0.10   # chunk's text actually mentions a course code from the query
PROSE_BOOST = 0.05    # chunk is a narrative review rather than a table row


def is_tabular(meta: dict) -> bool:
    """True if a chunk came from a table (CSV) rather than prose.

    Course-rating tables and the grade dataset are useful but read as rows of
    numbers; we use this to gently prefer narrative reviews when scores are close.
    """
    path = str(meta.get("source_path", "")).lower()
    doc_type = str(meta.get("doc_type", "")).lower()
    return path.endswith(".csv") or "csv" in doc_type or "dataset" in doc_type


def extract_course_numbers(query: str) -> list[str]:
    """Pull canonical course codes (e.g. 'CS 425') out of a query string.

    Short questions like "Is CS 425 hard?" carry a strong literal signal that a
    small embedding model under-weights. Surfacing the course code lets us
    constrain the search to chunks that actually mention it.
    """
    codes: list[str] = []
    for subject, number in _COURSE_RE.findall(query):
        code = f"{subject.upper()} {number}"
        if code not in codes:
            codes.append(code)
    return codes


def _collect_candidates(result: dict, pool: dict) -> None:
    """Add a Chroma query's rows to the candidate ``pool`` keyed by chunk id.

    De-duplicates across the two queries (course-filtered + plain vector) so a
    chunk found by both is scored once.
    """
    for cid, doc, meta, dist in zip(
        result["ids"][0], result["documents"][0],
        result["metadatas"][0], result["distances"][0],
    ):
        if cid in pool:
            continue
        pool[cid] = {
            "text": doc,
            "source": meta.get("source", ""),
            "doc_type": meta.get("doc_type", ""),
            "chunk_index": meta.get("chunk_index", ""),
            "similarity": round(1.0 - dist, 4),     # raw cosine similarity
            "distance": round(dist, 4),
            "metadata": meta,                        # full metadata, nothing dropped
        }


def retrieve(query: str, k: int = 5, course_filter: bool = True) -> list[dict]:
    """Return the top-k most relevant chunks for ``query``.

    The query is embedded with the *same* model. Candidates are gathered from
    two sources and merged into one pool so neither signal is lost:
      (a) a course-filtered query (Chroma ``where_document`` $contains) -- so
          chunks that actually mention a queried course code are considered even
          when their raw cosine similarity is low;
      (b) a plain vector query -- so the most semantically similar chunks are
          considered even when they don't name the code.

    Every candidate is then ranked by a *blended* score:
        rank_score = cosine_similarity
                     + COURSE_BONUS (if the chunk text mentions a queried code)
                     + PROSE_BOOST  (if the chunk is narrative rather than a table)
    The bonuses are small, so they only reshuffle near-ties; a clearly more
    similar chunk still leads. Each hit carries the chunk text, full metadata,
    similarity, distance, and rank_score.
    """
    collection = get_collection()
    query_embedding = embed_texts([query])
    codes = extract_course_numbers(query) if course_filter else []

    pool_n = max(k * 4, 20)   # gather a wider pool than k, then re-rank down to k
    pool: dict[str, dict] = {}

    if codes:
        clauses = [{"$contains": c} for c in codes]
        where_document = clauses[0] if len(clauses) == 1 else {"$or": clauses}
        _collect_candidates(collection.query(
            query_embeddings=query_embedding, n_results=pool_n,
            where_document=where_document,
            include=["documents", "metadatas", "distances"]), pool)

    _collect_candidates(collection.query(
        query_embeddings=query_embedding, n_results=pool_n,
        include=["documents", "metadatas", "distances"]), pool)

    hits = list(pool.values())
    for h in hits:
        mentions_code = any(c in h["text"] for c in codes)
        bonus = (COURSE_BONUS if mentions_code else 0.0) \
            + (0.0 if is_tabular(h["metadata"]) else PROSE_BOOST)
        h["course_filtered"] = mentions_code           # text mentions a queried code?
        h["rank_score"] = round(h["similarity"] + bonus, 4)

    hits.sort(key=lambda h: h["rank_score"], reverse=True)
    return hits[:k]


# ---------------------------------------------------------------------------
# Pretty printing + entry point
# ---------------------------------------------------------------------------
def print_results(query: str, hits: list[dict]) -> None:
    """Print retrieval results in a readable form."""
    codes = extract_course_numbers(query)
    note = f"  (course filter: {', '.join(codes)})" if codes else ""
    print(f"\nQuery: {query!r}{note}")
    print(f"Top {len(hits)} results:\n" + "=" * 70)
    for rank, hit in enumerate(hits, 1):
        snippet = " ".join(hit["text"].split())
        if len(snippet) > 320:
            snippet = snippet[:320] + " ..."
        tag = "[course-match]" if hit.get("course_filtered") else "[vector]"
        print(f"[{rank}] similarity={hit['similarity']:.4f} {tag}  "
              f"source={hit['source']}  doc_type={hit['doc_type']}  "
              f"chunk_index={hit['chunk_index']}")
        print(f"    {snippet}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed chunks into ChromaDB and run top-k similarity retrieval."
    )
    parser.add_argument("--query", default="Is CS 425 hard?",
                        help='Search query (default: "Is CS 425 hard?").')
    parser.add_argument("-k", "--top-k", type=int, default=5,
                        help="Number of results to return (default: 5).")
    parser.add_argument("--rebuild", action="store_true",
                        help="Delete and rebuild the collection from chunks.jsonl.")
    args = parser.parse_args()

    collection = get_collection()
    # Build the index if it's empty or a rebuild was requested.
    if args.rebuild or collection.count() == 0:
        build_index(rebuild=args.rebuild)
    else:
        print(f"Using existing ChromaDB collection '{COLLECTION_NAME}' "
              f"with {collection.count()} chunks (use --rebuild to refresh).")

    print_results(args.query, retrieve(args.query, k=args.top_k))


if __name__ == "__main__":
    main()

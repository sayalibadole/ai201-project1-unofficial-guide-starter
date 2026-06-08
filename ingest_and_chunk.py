"""
ingest_and_chunk.py
====================

Milestone 3 of "The Unofficial Guide" RAG system: **ingestion + chunking**.

Domain
------
Consolidated student feedback on UIUC MCS courses and professors (Rate My
Professor, UIUCMCS.org, r/UIUC_MCS, Coursicle, Medium/Quora posts, GPA/grade
datasets, etc.). Official UIUC pages don't aggregate this, so the value is in
pulling it into one searchable place.

Why local files are the primary source
---------------------------------------
Several target sites (Rate My Professors, Reddit, Quora, Coursicle) render their
content with JavaScript, so a plain ``requests`` download returns an empty
shell. The reliable workaround is to collect the review text by hand (save the
page as PDF/HTML, copy text into a .txt/.md, or export a table to .csv) and drop
those files into the ``documents/`` directory. This script ingests them.

What this script does
---------------------
1. Recursively scans a local directory (default ``documents/``) for supported
   files: .txt, .md, .html/.htm, .pdf, .csv, .json.
2. Extracts clean text from each file based on its type:
     - HTML  -> strip scripts/styles/nav/cookie banners/ads/share widgets.
     - PDF   -> extract text page by page (pdfplumber, then pypdf fallback).
     - CSV   -> render each row as labeled "Header: value | ..." text.
     - JSON  -> flatten to readable "key: value" lines.
     - TXT/MD-> normalize whitespace.
3. Preserves metadata: source name, document type, original URL, and the local
   file path. A SOURCE_METADATA map ties known file names back to the source
   table; unknown files fall back to inference.
4. Splits each document into ~300-token chunks with ~50-token overlap using
   LangChain's RecursiveCharacterTextSplitter (with character-based fallbacks
   when LangChain / tiktoken aren't installed).
5. Writes cleaned documents to ``documents.jsonl`` and chunks to ``chunks.jsonl``
   (one JSON object per line, with metadata + chunk index).

Pipeline (this file covers the first two stages):
    Document Ingestion  ->  Chunking  ->  Embedding+VectorStore  ->  Retrieval  ->  Generation

Run:
    python ingest_and_chunk.py
    python ingest_and_chunk.py --data-dir documents --out-dir .

PDF support needs one of:  pip install pdfplumber   (preferred)  OR  pip install pypdf
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional dependencies. The script degrades gracefully so it can run before
# `pip install langchain-text-splitters beautifulsoup4 tiktoken lxml pdfplumber`.
# ---------------------------------------------------------------------------
try:
    from bs4 import BeautifulSoup  # type: ignore

    _HAVE_BS4 = True
except ImportError:  # pragma: no cover
    _HAVE_BS4 = False

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore

    _HAVE_LANGCHAIN = True
except ImportError:  # older LangChain layout
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore

        _HAVE_LANGCHAIN = True
    except ImportError:  # pragma: no cover
        _HAVE_LANGCHAIN = False

try:
    import tiktoken  # type: ignore

    _HAVE_TIKTOKEN = True
except ImportError:  # pragma: no cover
    _HAVE_TIKTOKEN = False

# PDF: prefer pdfplumber (better layout handling), fall back to pypdf.
_PDF_ENGINE = None
try:
    import pdfplumber  # type: ignore

    _PDF_ENGINE = "pdfplumber"
except ImportError:
    try:
        from pypdf import PdfReader  # type: ignore

        _PDF_ENGINE = "pypdf"
    except ImportError:  # pragma: no cover
        _PDF_ENGINE = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR = Path("documents")          # where local source files live
SUPPORTED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".pdf", ".csv", ".json"}

# Chunking targets (in *tokens*).
TARGET_CHUNK_TOKENS = 150   # smaller chunks -> tighter, single-opinion units
CHUNK_OVERLAP_TOKENS = 25   # ~1/6 overlap, proportional to the 150-token size

# Character-based approximation when no real tokenizer is available (~4 chars/token).
CHARS_PER_TOKEN = 4

# HTML elements that never contain review content -- removed wholesale.
_HTML_NOISE_TAGS = [
    "script", "style", "noscript", "template", "svg", "iframe",
    "nav", "header", "footer", "aside", "form", "button",
]

# Substrings (matched against id/class/role) that signal boilerplate:
# nav menus, cookie banners, ads, share buttons, repeated headers, etc.
_HTML_NOISE_HINTS = [
    "cookie", "consent", "gdpr", "banner", "advert", "ad-", "ads", "sponsor",
    "promo", "nav", "menu", "navbar", "header", "footer", "sidebar",
    "breadcrumb", "share", "social", "subscribe", "newsletter", "signup",
    "login", "modal", "popup", "overlay", "skip-link", "pagination",
    "related", "recommend", "comment-form", "toolbar",
]


# ---------------------------------------------------------------------------
# Source metadata: map a file-name stem to its provenance.
# ---------------------------------------------------------------------------
# Lets a chunk be traced back to "Rate My Professor" + original URL even though
# the data now lives in a local file. Keys are matched as substrings of the
# (lower-cased) file stem, so "rate_my_prof_reviews.txt" matches "rate_my_prof".
SOURCE_METADATA: dict[str, dict[str, str]] = {
    "rate_my_prof":    {"source": "Rate My Professor",                  "doc_type": "Site (Rate My Professor)",  "url": "https://www.ratemyprofessors.com/search/professors/1112?q=*&did=11"},
    "ratemyprof":      {"source": "Rate My Professor",                  "doc_type": "Site (Rate My Professor)",  "url": "https://www.ratemyprofessors.com/search/professors/1112?q=*&did=11"},
    "citl":            {"source": "Professors ranked excellent (CITL)", "doc_type": "College Webpage",           "url": "https://siebelschool.illinois.edu/news/illinois-cs-places-28-faculty-on-citl-list-of-teachers-ranked-as-excellent-by-their-students"},
    "excellent_prof":  {"source": "Professors ranked excellent (CITL)", "doc_type": "College Webpage",           "url": "https://siebelschool.illinois.edu/news/illinois-cs-places-28-faculty-on-citl-list-of-teachers-ranked-as-excellent-by-their-students"},
    "uiucmcs":         {"source": "UIUC MCS course reviews",            "doc_type": "Webpage",                   "url": "https://uiucmcs.org/"},
    "course_review":   {"source": "UIUC MCS course reviews",            "doc_type": "Webpage",                   "url": "https://uiucmcs.org/"},
    "medium":          {"source": "Student Blog",                       "doc_type": "Medium",                    "url": "https://medium.com/@suvoo/the-actual-masters-experience-usa-17ed4adc2af3"},
    "quora":           {"source": "Student Discussions",                "doc_type": "Thread (Quora)",            "url": "https://www.quora.com/What-courses-in-UIUC-MCS-are-excellent-and-should-not-be-missed"},
    "reddit":          {"source": "UIUC MCS Reddit",                    "doc_type": "Subreddit (r/UIUC_MCS)",    "url": "https://www.reddit.com/r/UIUC_MCS/"},
    "coursicle_prof":  {"source": "Coursicle - professor reviews",      "doc_type": "Webpage",                   "url": "https://www.coursicle.com/illinois/professors/"},
    "coursicle":       {"source": "Coursicle - course reviews",         "doc_type": "Webpage",                   "url": "https://www.coursicle.com/illinois/"},
    "grade_disparity": {"source": "Grade disparity between courses",    "doc_type": "Webpage",                   "url": "https://waf.cs.illinois.edu/discovery/grade_disparity_between_sections_at_uiuc/"},
    "gpa":             {"source": "GPA Dataset",                        "doc_type": "Github Repo",               "url": "https://github.com/wadefagen/datasets/tree/main/gpa"},
}

# Generic fallback labels by extension when no SOURCE_METADATA key matches.
_EXT_DOC_TYPE = {
    ".csv": "Tabular Dataset (CSV)",
    ".json": "Structured Data (JSON)",
    ".html": "Web Page (HTML)",
    ".htm": "Web Page (HTML)",
    ".pdf": "PDF Document",
    ".md": "Markdown Document",
    ".txt": "Plain Text",
}


def resolve_metadata(path: Path) -> dict[str, str]:
    """Return {source, doc_type, url} for a file.

    Looks for a known keyword in the lower-cased file stem (so a chunk can be
    attributed to "Reddit" vs. "Coursicle" with its original URL). Falls back to
    a generic type derived from the extension when nothing matches.
    """
    stem = path.stem.lower()
    for key, meta in SOURCE_METADATA.items():
        if key in stem:
            return meta
    return {
        "source": path.stem,
        "doc_type": _EXT_DOC_TYPE.get(path.suffix.lower(), "Unknown"),
        "url": "",
    }


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------
def normalize_whitespace(text: str) -> str:
    """Collapse excessive whitespace while keeping paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _element_is_noise(element) -> bool:
    """Return True if a BeautifulSoup element looks like boilerplate (id/class/role)."""
    if getattr(element, "attrs", None) is None:  # already-decomposed descendant
        return False
    attr_values: list[str] = []
    for attr in ("id", "class", "role"):
        value = element.get(attr)
        if value:
            attr_values.extend(value if isinstance(value, list) else [value])
    haystack = " ".join(str(v) for v in attr_values).lower()
    return any(hint in haystack for hint in _HTML_NOISE_HINTS)


def clean_html(raw_html: str) -> str:
    """Extract clean, readable visible text from raw HTML.

    1. Drop tags that never hold content (script/style/nav/header/footer/...).
    2. Drop elements whose id/class/role marks them as cookie banners, ads,
       navigation, or share widgets.
    3. Extract remaining visible text and normalize whitespace.
    Falls back to a regex stripper when BeautifulSoup isn't installed.
    """
    if _HAVE_BS4:
        try:
            soup = BeautifulSoup(raw_html, "lxml")
        except Exception:
            soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(_HTML_NOISE_TAGS):
            tag.decompose()
        for element in soup.find_all(True):
            if _element_is_noise(element):
                element.decompose()
        return normalize_whitespace(soup.get_text(separator="\n"))

    # Regex fallback (no BeautifulSoup)
    cleaned = re.sub(r"<(script|style|noscript|template)[^>]*>.*?</\1>", " ",
                     raw_html, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<(/?(p|div|br|li|tr|h[1-6]))[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    for entity, char in {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
    }.items():
        cleaned = cleaned.replace(entity, char)
    return normalize_whitespace(cleaned)


def _is_number(value: str) -> bool:
    """Return True if a string parses as a float (helper for CSV header detection)."""
    try:
        float(value.strip())
        return True
    except (TypeError, ValueError):
        return False


def csv_to_text(raw_csv: str) -> str:
    """Convert CSV content into labeled, one-line-per-row natural text.

    Each data row becomes "Header: value | Header: value | ..." so an embedding
    model sees self-describing facts instead of bare cells. Empty cells are
    dropped. A first row that is all-numeric is treated as headerless.
    """
    rows = list(csv.reader(io.StringIO(raw_csv)))
    if not rows:
        return ""
    header = [h.strip() for h in rows[0]]
    looks_like_header = any(not _is_number(cell) for cell in header)

    lines: list[str] = []
    for row in (rows[1:] if looks_like_header else rows):
        if not any(cell.strip() for cell in row):
            continue
        if looks_like_header:
            parts = [f"{header[i]}: {cell.strip()}"
                     for i, cell in enumerate(row)
                     if i < len(header) and cell.strip()]
        else:
            parts = [cell.strip() for cell in row if cell.strip()]
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def json_to_text(raw_json: str) -> str:
    """Flatten JSON into readable 'key: value' lines (list of objects, or object)."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return normalize_whitespace(raw_json)

    def render_obj(obj: dict) -> str:
        parts = []
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"{key}: {value}")
        return "\n".join(parts)

    if isinstance(data, list):
        blocks = [render_obj(i) if isinstance(i, dict) else str(i) for i in data]
        return normalize_whitespace("\n\n".join(blocks))
    if isinstance(data, dict):
        return normalize_whitespace(render_obj(data))
    return normalize_whitespace(json.dumps(data, ensure_ascii=False, indent=2))


def pdf_to_text(path: Path) -> str:
    """Extract text from a PDF, page by page.

    Uses pdfplumber when available (best layout fidelity), else pypdf. Raises a
    clear RuntimeError if neither is installed so the user knows to install one.
    Page texts are joined with blank lines and then whitespace-normalized.
    """
    if _PDF_ENGINE is None:
        raise RuntimeError(
            "No PDF library installed. Run `pip install pdfplumber` (or pypdf) to ingest PDFs."
        )

    pages: list[str] = []
    if _PDF_ENGINE == "pdfplumber":
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
    else:  # pypdf
        reader = PdfReader(str(path))
        for page in reader.pages:
            pages.append(page.extract_text() or "")

    return normalize_whitespace("\n\n".join(pages))


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def extract_text(path: Path) -> str:
    """Load one file and return cleaned plain text based on its extension."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_to_text(path)

    raw = path.read_text(encoding="utf-8", errors="ignore")
    if ext in (".html", ".htm"):
        return clean_html(raw)
    if ext == ".csv":
        return csv_to_text(raw)
    if ext == ".json":
        return json_to_text(raw)
    return normalize_whitespace(raw)  # .txt and .md


def scan_documents(data_dir: Path):
    """Recursively yield every supported file under ``data_dir`` (sorted)."""
    for path in sorted(data_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def load_documents(data_dir: Path) -> list[dict]:
    """Ingest every supported file under ``data_dir`` into document records.

    Each record: doc_id, source, doc_type, url, source_path, text, char_count,
    token_count. Empty/unreadable files are skipped with a warning.
    """
    documents: list[dict] = []
    for path in scan_documents(data_dir):
        meta = resolve_metadata(path)
        try:
            text = extract_text(path)
        except Exception as exc:  # keep going if one file is malformed/unsupported
            print(f"  ! Skipping {path.name} ({exc})", file=sys.stderr)
            continue
        if not text.strip():
            print(f"  - Empty after cleaning: {path.name}", file=sys.stderr)
            continue

        rel = path.relative_to(data_dir).as_posix()
        documents.append({
            "doc_id": rel,
            "source": meta["source"],
            "doc_type": meta["doc_type"],
            "url": meta["url"],
            "source_path": path.as_posix(),
            "text": text,
            "char_count": len(text),
            "token_count": count_tokens(text),
        })
        print(f"  + {rel}  [{meta['source']}]  {len(text)} chars")
    return documents


# ---------------------------------------------------------------------------
# Tokenization / chunking
# ---------------------------------------------------------------------------
_ENCODER = None
if _HAVE_TIKTOKEN:
    try:
        # cl100k_base matches text-embedding-3-* and GPT-4o.
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover
        _ENCODER = None


def count_tokens(text: str) -> int:
    """Token count via tiktoken when available, else the ~4-chars/token rule."""
    if _ENCODER is not None:
        return len(_ENCODER.encode(text))
    return max(1, len(text) // CHARS_PER_TOKEN)


def build_splitter():
    """Construct the chunker.

    Preferred: LangChain RecursiveCharacterTextSplitter measured in *tokens* via
    tiktoken, so "~300 tokens / 50 overlap" is exact. Recursive separators
    (paragraph -> line -> sentence -> word) keep coherent opinions about
    workload/difficulty/grading/instructor together rather than cutting
    mid-sentence. Fallbacks: char-sized splitter, or pure-Python splitter.
    """
    if not _HAVE_LANGCHAIN:
        return None
    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]
    if _ENCODER is not None:
        return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name="cl100k_base",
            chunk_size=TARGET_CHUNK_TOKENS,
            chunk_overlap=CHUNK_OVERLAP_TOKENS,
            separators=separators,
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=TARGET_CHUNK_TOKENS * CHARS_PER_TOKEN,
        chunk_overlap=CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN,
        length_function=len,
        separators=separators,
    )


def _fallback_split(text: str) -> list[str]:
    """Pure-Python recursive splitter used when LangChain isn't installed."""
    chunk_chars = TARGET_CHUNK_TOKENS * CHARS_PER_TOKEN
    overlap_chars = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN
    separators = ["\n\n", "\n", ". ", " "]

    def split_recursive(segment: str, seps: list[str]) -> list[str]:
        if len(segment) <= chunk_chars or not seps:
            return [segment]
        sep = seps[0]
        pieces = segment.split(sep) if sep else list(segment)
        out: list[str] = []
        for piece in pieces:
            if len(piece) > chunk_chars:
                out.extend(split_recursive(piece, seps[1:]))
            else:
                out.append(piece)
        return out

    pieces = split_recursive(text, separators)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = (current + " " + piece).strip() if current else piece
        if len(candidate) > chunk_chars and current:
            chunks.append(current.strip())
            current = (current[-overlap_chars:] + " " + piece).strip()
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c.strip()]


def chunk_documents(documents: list[dict]) -> list[dict]:
    """Split each cleaned document into overlapping chunk dictionaries.

    Each chunk: chunk_id, text, source, doc_type, url, source_path,
    chunk_index, num_chunks, char_count, token_count.
    """
    splitter = build_splitter()
    all_chunks: list[dict] = []
    for doc in documents:
        pieces = splitter.split_text(doc["text"]) if splitter else _fallback_split(doc["text"])
        for i, piece in enumerate(pieces):
            piece = piece.strip()
            if not piece:
                continue
            all_chunks.append({
                "chunk_id": f"{doc['doc_id']}::{i}",
                "doc_id": doc["doc_id"],          # source document (file) name
                "text": piece,
                "source": doc["source"],
                "doc_type": doc["doc_type"],
                "url": doc["url"],
                "source_path": doc["source_path"],
                "chunk_index": i,
                "num_chunks": len(pieces),
                "char_count": len(piece),
                "token_count": count_tokens(piece),
            })
    return all_chunks


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_jsonl(records: list[dict], path: Path) -> None:
    """Write a list of dicts to ``path`` as JSON Lines (one object per line)."""
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest and chunk local UIUC MCS review files for a RAG system."
    )
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="Directory to recursively scan for source files (default: documents).")
    parser.add_argument("--out-dir", default=".",
                        help="Directory for documents.jsonl and chunks.jsonl (default: .).")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not data_dir.exists():
        sys.exit(f"Data directory '{data_dir}' does not exist. Create it and add source files.")

    # Report active engines so the run is reproducible.
    print("Engines:")
    print(f"  HTML cleaner : {'BeautifulSoup' if _HAVE_BS4 else 'regex fallback'}")
    print(f"  PDF reader   : {_PDF_ENGINE or 'NONE (install pdfplumber or pypdf to ingest PDFs)'}")
    print(f"  Splitter     : {'LangChain RecursiveCharacterTextSplitter' if _HAVE_LANGCHAIN else 'pure-Python fallback'}")
    print(f"  Tokenizer    : {'tiktoken cl100k_base' if _ENCODER else '~4 chars/token approximation'}")
    print()

    print(f"Scanning '{data_dir}' for {sorted(SUPPORTED_EXTENSIONS)} ...")
    documents = load_documents(data_dir)
    if not documents:
        sys.exit("No supported documents found. Add files to the data directory and retry.")

    print(f"\nChunking {len(documents)} document(s) "
          f"(~{TARGET_CHUNK_TOKENS} tokens/chunk, {CHUNK_OVERLAP_TOKENS}-token overlap) ...")
    chunks = chunk_documents(documents)

    docs_path = out_dir / "documents.jsonl"
    chunks_path = out_dir / "chunks.jsonl"
    write_jsonl(documents, docs_path)
    write_jsonl(chunks, chunks_path)

    total_tokens = sum(c["token_count"] for c in chunks)
    avg_tokens = total_tokens / len(chunks) if chunks else 0
    print("\nDone.")
    print(f"  Documents : {len(documents)}  -> {docs_path}")
    print(f"  Chunks    : {len(chunks)}  -> {chunks_path}")
    print(f"  Avg tokens/chunk : {avg_tokens:.1f}")


if __name__ == "__main__":
    main()

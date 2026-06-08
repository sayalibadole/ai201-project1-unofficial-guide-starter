"""
app.py
======

Milestone 5 of "The Unofficial Guide" RAG system: **grounded generation + UI**.

Pipeline position:
    ... -> ChromaDB Vector Store -> Retrieval -> [GENERATION + GRADIO] (this file)

What this file does
-------------------
1. Retrieves the top-k most relevant chunks for a user question (reusing the
   retriever in embedding_retrieval.py -- retrieval ALWAYS runs before the LLM).
2. Builds a strongly-grounded prompt: the LLM may answer ONLY from the retrieved
   context, must not use outside knowledge, and must refuse with a fixed
   sentence when the context is insufficient.
3. Calls Groq's ``llama-3.3-70b-versatile`` to generate the answer.
4. Appends a Sources list **programmatically** from the retrieval metadata --
   citations are guaranteed by code, not by trusting the LLM to remember them.
5. Serves everything through a Gradio interface.

Functions (as required):
    load_llm()                          -> Groq client (singleton)
    generate_answer(question, chunks)   -> raw answer string from the LLM
    answer_question(question)           -> retrieval + generation + sources (UI fn)
    launch_gradio()                     -> start the web interface

Dependencies:  pip install groq python-dotenv gradio
Set GROQ_API_KEY in a .env file (get a free key at https://console.groq.com).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from groq import Groq

import embedding_retrieval as er

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LLM_MODEL = "llama-3.3-70b-versatile"   # Groq-hosted Llama 3.3 70B
TOP_K = 5                                # chunks retrieved per question

# The exact sentence the system must return when the context is insufficient.
REFUSAL_MESSAGE = (
    "I don't have enough information in the retrieved documents to answer that question."
)

# Strong grounding system prompt. This is the core safety mechanism: it confines
# the model to the supplied context and forbids outside knowledge / guessing.
SYSTEM_PROMPT = f"""You are a factual assistant for UIUC MCS course and professor reviews.
You answer questions about course workload, difficulty, grading, projects, and
instructor quality using ONLY the context provided to you in each request.

STRICT RULES:
1. Use ONLY the information in the "Context" section. Treat it as your only source of truth.
2. Do NOT use any outside, prior, or general knowledge. Do NOT guess or speculate.
3. Do NOT invent course names, professor names, numbers, ratings, or sources.
4. If the Context does not contain enough information to answer the question, reply with
   EXACTLY this sentence and nothing else:
   "{REFUSAL_MESSAGE}"
5. Do NOT write your own "Sources" list or citations; the application adds sources separately.

Answer concisely and only with what the context supports."""

# Lazily-created Groq client so importing this module doesn't require a key.
_CLIENT: Groq | None = None


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------
def load_llm() -> Groq:
    """Load the GROQ_API_KEY from .env and return a (cached) Groq client.

    Groq's Python SDK mirrors the OpenAI chat-completions API; the client is
    created once with the API key and reused for every request.
    """
    global _CLIENT
    if _CLIENT is None:
        load_dotenv()  # read GROQ_API_KEY from .env into the environment
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_key_here":
            raise RuntimeError(
                "GROQ_API_KEY is missing. Copy .env.example to .env and set a real key "
                "from https://console.groq.com."
            )
        _CLIENT = Groq(api_key=api_key)
    return _CLIENT


# ---------------------------------------------------------------------------
# Prompt building + source attribution
# ---------------------------------------------------------------------------
def build_context(retrieved_chunks: list[dict]) -> str:
    """Render retrieved chunks into a numbered Context block for the prompt."""
    blocks = []
    for i, chunk in enumerate(retrieved_chunks, 1):
        source = chunk.get("source", "unknown")
        blocks.append(f"[{i}] (source: {source})\n{chunk.get('text', '').strip()}")
    return "\n\n".join(blocks)


def build_messages(question: str, retrieved_chunks: list[dict]) -> list[dict]:
    """Build the system + user messages for the chat completion."""
    user_content = (
        f"Context:\n{build_context(retrieved_chunks)}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the context above."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def extract_sources(retrieved_chunks: list[dict]) -> list[str]:
    """Return the unique source names from retrieval metadata, in order.

    This is the programmatic source of truth for citations -- it never depends
    on the LLM's output.
    """
    sources: list[str] = []
    for chunk in retrieved_chunks:
        source = chunk.get("source")
        if source and source not in sources:
            sources.append(source)
    return sources


def _is_refusal(answer: str) -> bool:
    """True if the model returned the (insufficient-context) refusal sentence."""
    normalized = answer.strip().lower().rstrip(".")
    return REFUSAL_MESSAGE.lower().rstrip(".") in normalized


def format_output(answer: str, retrieved_chunks: list[dict]) -> str:
    """Format the final UI string: the answer, plus a programmatic Sources list.

    Sources are appended ONLY when the model actually answered -- if it refused
    for lack of context, listing sources would be misleading, so we omit them.
    """
    out = f"Answer:\n\n{answer.strip()}"
    if not _is_refusal(answer):
        sources = extract_sources(retrieved_chunks)
        if sources:
            out += "\n\nSources:\n" + "\n".join(f"- {s}" for s in sources)
    return out


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def generate_answer(question: str, retrieved_chunks: list[dict]) -> str:
    """Generate a grounded answer from the retrieved chunks using Groq.

    Returns the raw answer text (no Sources list -- that is appended later by
    ``format_output``). ``temperature=0`` makes generation deterministic and
    minimizes the chance of the model drifting away from the context.
    """
    if not retrieved_chunks:
        # No evidence retrieved -> refuse without calling the LLM at all.
        return REFUSAL_MESSAGE

    client = load_llm()
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=build_messages(question, retrieved_chunks),
        temperature=0.0,      # deterministic, grounding-friendly
        max_tokens=512,
    )
    return completion.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Orchestration (retrieval -> generation -> sources)  == the Gradio callback
# ---------------------------------------------------------------------------
def answer_question(question: str) -> str:
    """End-to-end: retrieve context, generate a grounded answer, append sources.

    This is the function wired into Gradio. Retrieval ALWAYS runs first, so the
    model only ever sees retrieved evidence.
    """
    question = (question or "").strip()
    if not question:
        return "Please enter a question about UIUC MCS courses or professors."

    # 1. Retrieve (always before generation).
    retrieved_chunks = er.retrieve(question, k=TOP_K)

    # 2. No evidence -> grounded refusal, no sources.
    if not retrieved_chunks:
        return f"Answer:\n\n{REFUSAL_MESSAGE}"

    # 3. Generate, then 4. append sources programmatically from metadata.
    try:
        answer = generate_answer(question, retrieved_chunks)
    except Exception as exc:  # surface API/config errors clearly in the UI
        return f"Error contacting the language model: {exc}"

    return format_output(answer, retrieved_chunks)


# ---------------------------------------------------------------------------
# Gradio interface
# ---------------------------------------------------------------------------
def launch_gradio():
    """Build and launch the Gradio web interface."""
    import gradio as gr

    demo = gr.Interface(
        fn=answer_question,                 # retrieval + generation + sources
        inputs="text",
        outputs="text",
        title="UIUC MCS Course & Professor Review Assistant",
        description=(
            "Ask about UIUC MCS course workload, difficulty, grading, or instructor "
            "quality. Answers are grounded only in retrieved student reviews, with "
            "sources listed below each answer."
        ),
        examples=[
            "Is CS 425 hard?",
            "What is the workload for CS 410 Text Information Systems?",
            "Which courses do students recommend most?",
        ],
    )
    demo.launch()
    return demo


if __name__ == "__main__":
    launch_gradio()

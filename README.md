# The Unofficial Guide — Project 1

> **How to use this template:**
> Complete each section *after* you've built and tested the corresponding part of your system.
> Do not write placeholder text — if a section isn't done yet, leave it blank and come back.
> Every section below is required for submission. One-liners will not receive full credit.

---

## Domain

<!-- What topic or category of knowledge does your system cover?
     Why is this knowledge valuable, and why is it hard to find through official channels?
     Example: "Student reviews of CS professors at [university] — useful because official
     course descriptions don't reflect teaching style, exam difficulty, or workload." -->
Topic Covered: Course and Professor reviews at UIUC - MCS program. 

This resource fills a gap not addressed by official UIUC websites by consolidating student feedback in one place. Instead of searching across multiple platforms, students can easily access reviews and insights to help inform their course and instructor selections.

---

## Document Sources

<!-- List every source you collected documents from.
     Be specific: include URLs, subreddit names, forum thread titles, or file names.
     Aim for variety — sources that together cover different subtopics or perspectives. -->

| # | Source | Type | URL or file path |
|---|--------|------|-----------------|
| 1 |Rate My Professor |Site |https://www.ratemyprofessors.com/search/professors/1112?q=*&did=11 |
| 2 |List of professors ranked excellent |College Webpage |https://siebelschool.illinois.edu/news/illinois-cs-places-28-faculty-on-citl-list-of-teachers-ranked-as-excellent-by-their-students |
| 3 |UIUC MCS course reviews|Webpage |https://uiucmcs.org/ |
| 4 |Student Blog |Medium |https://medium.com/@suvoo/the-actual-masters-experience-usa-17ed4adc2af3 |
| 5 |Student Discussions | Thread|https://www.quora.com/What-courses-in-UIUC-MCS-are-excellent-and-should-not-be-missed |
| 6 |UIUC MCS Reddit | Subreddit |https://www.reddit.com/r/UIUC_MCS/|
| 7 |Coursicle - course reviews |Webpage |https://www.coursicle.com/illinois/ |
| 8 |Grade disparity between courses |Webpage |[https://waf.cs.illinois.edu/discovery/grade_disparity_between_sections_at_uiuc/](https://waf.cs.illinois.edu/visualizations/Grade-Disparities-and-Accolades-by-Instructor/) |
| 9 |Coursicle - professor reviews | Webpage|https://www.coursicle.com/illinois/professors/ |
| 10 |GPA Dataset | Github Repo | https://github.com/wadefagen/datasets/tree/main/gpa |

---

## Chunking Strategy

<!-- Describe your chunking approach with enough specificity that someone else could reproduce it.
     Include:
     - Chunk size (characters or tokens) and why that size fits your documents
     - Overlap size and why (or why not) you used overlap
     - Any preprocessing you did before chunking (e.g., stripping HTML, removing headers)
     - What your final chunk count was across all documents -->

**Chunk size:**
150 tokens per chunk 
**Overlap:**
25 tokens overlap
**Why these choices fit your documents:**
Our corpus consists primarily of:

Student course reviews
Reddit comments and discussion threads
RateMyProfessor reviews
Course writeups and blog posts
UIUCMCS reviews

Most reviews are relatively short (1–5 paragraphs) and contain a single opinion or experience about workload, difficulty, projects, grading, or teaching quality. Because the documents are opinion-based rather than long technical manuals, very large chunks would combine multiple unrelated ideas and reduce retrieval precision.

A chunk size of approximately 150 tokens is large enough to preserve the context of a student's review while remaining focused on a specific experience. For example, a review discussing workload, project difficulty, and instructor quality can usually fit within a single chunk, allowing the retrieval system to return a coherent opinion rather than fragmented sentences.

A 25-token overlap helps preserve information that may span chunk boundaries. For example, a reviewer might describe project difficulty at the end of one chunk and explain its impact on workload at the beginning of the next. The overlap ensures that important context is not lost and that either chunk remains retrievable.

---

## Embedding Model

<!-- Name the embedding model you used and explain your choice.
     Then answer: if you were deploying this system for real users and cost wasn't a constraint,
     what tradeoffs would you weigh in choosing a different model?
     Consider: context length limits, multilingual support, accuracy on domain-specific text,
     latency, and local vs. API-hosted. -->

**Model used:**
all-MiniLM-L6-v2 (from sentence-transformers), loaded with SentenceTransformer("all-MiniLM-L6-v2"). It produces 384-dimensional dense embeddings, runs locally (no API key, no per-call cost), and I store the vectors in ChromaDB with cosine similarity (hnsw:space: "cosine"), L2-normalizing embeddings at encode time.

I chose it because it fits this corpus and project constraints well:

Right size for short reviews. My chunks are small (~150 tokens) single opinions about workload/difficulty/grading. MiniLM's 256-token input window comfortably covers a whole chunk, so nothing gets truncated.
Fast and free, locally. Embedding all 80 chunks and every query takes well under a second on CPU, which keeps the ingest→retrieve loop tight while I iterate on chunking and ranking.
Strong quality-for-size. It's a widely-used, well-benchmarked general sentence embedder — good enough semantic similarity for English student reviews without the weight of a larger model.
Same model for documents and queries, so the vector spaces line up for honest cosine comparison.
Production tradeoff reflection:


**Production tradeoff reflection:**

If I were deploying for real users and cost weren't a constraint, I'd weigh:

Accuracy on domain-specific text. MiniLM is general-purpose and treats course codes ("CS 425") and professor names weakly — I had to add a course-code keyword filter on top of vector search to compensate. A larger, more capable embedder (e.g. bge-large-en-v1.5, e5-large-v2, or a hosted model like OpenAI text-embedding-3-large) would capture finer semantic distinctions and likely reduce my reliance on that keyword crutch.
Context length. MiniLM's ~256-token window is fine for 150-token chunks but would truncate larger ones. A long-context embedder (e.g. text-embedding-3-large at 8k tokens) would let me use bigger chunks that keep a full multi-paragraph review together — better for "summarize all opinions on X" queries.
Multilingual support. My sources are English-only, so this doesn't matter now; but if reviews appeared in other languages, I'd switch to a multilingual model (e.g. paraphrase-multilingual-MiniLM-L12-v2).
Latency vs. local control. Local MiniLM has zero network latency and keeps data on-device (good for privacy); an API-hosted model adds per-call latency and cost and sends text to a third party, but removes the need to host/scale the embedder myself.
Net call: for a small English review corpus, MiniLM is the pragmatic choice. At production scale with quality as the priority, I'd most likely move to a larger local model like bge-large-en-v1.5 (better accuracy, still self-hosted) before reaching for a paid API.


---

## Grounded Generation

<!-- Explain how your system enforces grounding — how does it prevent the LLM from answering
     beyond the retrieved documents?
     Describe both your system prompt (what instruction you gave the model) and any structural
     choices (e.g., how you formatted the context, whether you filtered low-relevance chunks).
     Do not just say "I told it to use the documents" — show the actual instruction or explain
     the mechanism. -->

**System prompt grounding instruction:**
The model receives this exact system prompt (from app.py), which confines it to the retrieved context and forbids outside knowledge:


You are a factual assistant for UIUC MCS course and professor reviews.
You answer questions about course workload, difficulty, grading, projects, and
instructor quality using ONLY the context provided to you in each request.

STRICT RULES:
1. Use ONLY the information in the "Context" section. Treat it as your only source of truth.
2. Do NOT use any outside, prior, or general knowledge. Do NOT guess or speculate.
3. Do NOT invent course names, professor names, numbers, ratings, or sources.
4. If the Context does not contain enough information to answer the question, reply with
   EXACTLY this sentence and nothing else:
   "I don't have enough information in the retrieved documents to answer that question."
5. Do NOT write your own "Sources" list or citations; the application adds sources separately.

Answer concisely and only with what the context supports.
The key instructions are: (1) treat the Context as the only source of truth, (2) an explicit refusal sentence for insufficient context so "I don't know" is a first-class, well-defined output rather than an invitation to guess, and (3) a ban on inventing the specific things this domain is prone to fabricate — course numbers, professor names, ratings.

**How source attribution is surfaced in the response:**
Sources are appended programmatically by the application, never generated by the LLM. The flow:

Retrieval returns chunks that each carry a source field in their metadata (e.g. UIUC MCS Reddit, UIUC MCS course reviews), set during ingestion.
After generation, extract_sources() collects those source values from the retrieved chunks — deduplicated and order-preserving — independent of anything the model wrote.
format_output() renders the answer followed by a Sources: block, one bullet per unique source.
So the response a user sees looks like:


Answer:

CS 425 Distributed Systems has a difficulty rating of 4.2 (on a scale of 1-5)
and a workload of 15.7 hours per week.

Sources:
- UIUC MCS course reviews
- UIUC MCS Reddit
- Professors ranked excellent (CITL)
  
---

## Evaluation Report

<!-- Run your 5 test questions from planning.md through your system and record the results.
     Be honest — a partially accurate or inaccurate result that you explain well is more
     valuable than a suspiciously perfect result. -->

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 |Is CS 425 considered a difficult course? |Yes, CS 425 (Distributed Systems / Cloud Computing Concepts) is generally considered a difficult but rewarding course in the UIUC MCS program.The rigor and workload of the course can vary depending on whether you are taking the 3-credit or 4-credit version, and whether you are taking it online (via Coursera) or on-campus |Yes, CS 425 (Distributed Systems) is considered a difficult course, with a difficulty rating of 4.2 out of 5, according to the course reviews. Additionally, a student mentioned that the C++ programming assignment and exams in CS 425 were challenging. |Relevant |Accurate |
| 2 |What is the workload like for CS 411? |The workload for CS 411 (Database Systems) in the UIUC MCS program is generally considered moderate but highly practical, requiring an average of 8 to 12 hours per week. It is often viewed as a highly manageable course that provides strong, industry-applicable skills |The workload for CS 411 is 5.9 hours per week.|Partially relevant|Accurate |
| 3 |Which MCS courses are considered the most useful for industry jobs? |CS 425, CS 411, 446, 498 |Based on the context, the following MCS courses are considered useful for industry jobs: 1. CS 445 Computational Photography (beneficial if you aim at an industry role in CV) 2. A Machine Learning class (served as a strong foundation for multiple ML engineering interviews) 3. CS 410 Text Information Systems (covered text retrieval, text mining, search engines, recommendation systems, and more) |Partially relevant |Partially accurate |
| 4 |How does CS 425 compare to CS 411 in workload? |CS 425 (Distributed Systems) requires a significantly higher time commitment than CS 411 (Database Systems). CS 425 is highly practical and conceptually rigorous, whereas CS 411 leans heavily on straightforward applied concepts and team projects, though workload can fluctuate based on your prior programming experience |CS 425 has a workload of 15.7 hours/week, while CS 411 has a workload of 5.9 hours/week. Therefore, CS 425 has a significantly higher workload than CS 411.|Relevant |Accurate |
| 5 |Which courses tend to have the highest average GPA? |In the UIUC MCS (Master of Computer Science) program, upper-level (400-level and above) courses generally have higher average GPAs than foundational weed-out courses. Electives like CS 410 (Text Information Systems) and CS 411 (Database Systems) are well-regarded by students for having manageable workloads and higher grading averages |Based on the context, the courses with the highest average GPA (as indicated by the percent of A's or 4.0s) are: - STAT 107 (62% with instructor Fagen-Ulmschneider, Wade) - ECE 314 (85% with instructor Katselis, Dimitrios and 62% with instructor Hajek, Bruce) These courses have the highest percentages of A's, suggesting they may have the highest average GPA. |Partially relevant |Partially accurate |

**Retrieval quality:** Relevant / Partially relevant / Off-target  
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

<!-- Identify at least one question where retrieval or generation did not work as expected.
     Write a specific explanation of *why* it failed, tied to a part of the pipeline.

     "The answer was wrong" is not an explanation.

     "The relevant information was split across a chunk boundary, so retrieval returned
     only half the context — the model didn't have enough to answer correctly" is an explanation.

     "The embedding model treated the professor's nickname as out-of-vocabulary and returned
     results from an unrelated review" is an explanation. -->

**Question that failed:**
"Which professors receive better reviews for CS 411?"

**What the system returned:**
I don't have enough information in the retrieved documents to answer that question.

**Root cause (tied to a specific pipeline stage):**
This is an ingestion / data-modeling + chunking failure, not a generation bug — in fact, generation behaved correctly by refusing instead of fabricating.

Answering the question requires joining two facts that live in different documents: (1) which professor teaches CS 411, and (2) that professor's review sentiment. In my corpus those facts are never co-located:

- Rate My Professors chunks have professor → quality/difficulty scores, but the reviews are not tagged with the course the professor teaches.
- UIUCMCS has CS 411's course-level ratings, but no instructor field.
- The grade-disparity dataset maps courses → instructors, but my curated version covers CS 341/241/233/340/423 etc. and does not include a CS 411 row — so there is no professor↔CS-411 link anywhere in the data.
  
Because retrieval returns whole chunks and cannot join across them, no single retrieved chunk contains both a professor name and CS 411 review sentiment. The grounding prompt then correctly forces a refusal, since the context genuinely lacks the answer. The information needed to answer is effectively absent from the corpus, and what fragments exist are split across sources with no shared key that chunking could keep together.

**What you would change to fix it:**
Close the data gap: add a source that ties professors to specific courses with sentiment — e.g. Coursicle's per-professor course reviews (which I couldn't scrape because the site is JS-rendered) or per-course RMP review text — so a professor↔CS-411 statement actually exists to retrieve.

Enrich metadata for structured retrieval: tag chunks with explicit course_number and professor fields during ingestion, then support a metadata where filter (e.g. course_number == "CS 411") so the retriever can target the right rows instead of relying on text similarity alone.

Multi-hop retrieval for join-style questions: first retrieve "who teaches CS 411," then issue a second retrieval for those professors' reviews, and pass both hops as context — letting the system assemble an answer that no single chunk holds.

---

## Spec Reflection

<!-- Reflect on how planning.md shaped your implementation.
     Answer both questions with at least 2–3 sentences each. -->

**One way the spec helped you during implementation:**
The planning document provided a clear structure for building the RAG pipeline by defining the document sources, chunking strategy, retrieval approach, and evaluation criteria before implementation began. Having these requirements documented made it easier to generate code using AI tools because the expected behavior of each component was already specified. The chunk size, overlap, metadata requirements, and grounding requirements also served as a checklist for verifying that the ingestion, retrieval, and generation stages were functioning correctly.

**One way your implementation diverged from the spec, and why:**
The original plan assumed that document content could be ingested directly from the provided URLs. During implementation, it became clear that several sources, including Rate My Professors, Reddit, Quora, and Coursicle, use JavaScript rendering or anti-scraping protections that prevented reliable extraction of the full review content through simple HTTP requests. As a result, the implementation shifted toward using locally saved content and manually collected review data for some sources to ensure that the ingestion and chunking pipeline had access to clean, complete text. This change improved data quality and retrieval performance while still preserving the overall goals of the project.

---

## AI Usage

<!-- Describe at least 2 specific instances where you used an AI tool during this project.
     For each: what did you give the AI as input, what did it produce, and what did you
     change, override, or direct differently?

     "I used Claude to help me code" is not sufficient.
     "I gave Claude my Chunking Strategy section from planning.md and asked it to implement
     chunk_text(). It returned a function using a fixed character split. I overrode the
     chunk size from 500 to 200 because my documents are short reviews, not long guides." -->

**Instance 1**

- *What I gave the AI:* I provided ChatGPT with the Document Sources, Chunking Strategy, and pipeline diagram sections from my planning document and asked it to generate an ingestion and chunking script for the RAG pipeline.
- *What it produced:* The AI produced a Python implementation that loaded documents, cleaned text, and split content into chunks using a text splitter.
- *What I changed or overrode:* After reviewing the generated code, I noticed that it initially assumed all data would be loaded from local files, while my project sources were primarily URLs. I modified the implementation to support collecting content from web sources and later adjusted the workflow to use locally saved documents for sources that were difficult to scrape, such as Rate My Professors, Reddit, Quora, and Coursicle. I also verified that the chunk size and overlap matched my specification of approximately 300 tokens with a 50-token overlap and added chunk inspection code to validate chunk quality before moving on to embeddings.

**Instance 2**

- *What I gave the AI:* I provided ChatGPT with the document sources and chunking requirements from my planning document and asked it to recommend a chunking strategy for the review-based dataset.
- *What it produced:* Based on the initial description, the AI suggested using chunk sizes of approximately 350 tokens with overlap between chunks to preserve context.
- *What I changed or overrode:* After testing the generated chunks, I found that many chunks contained multiple unrelated reviews or mixed together different opinions about courses and professors. Because the dataset consists primarily of short student reviews, discussion posts, and comments, larger chunks reduced retrieval precision by combining too many ideas into a single chunk. I adjusted the chunk size to approximately 150 tokens while keeping overlap between chunks. This produced more focused chunks that better represented individual reviews and improved retrieval relevance when testing course and professor-related queries.

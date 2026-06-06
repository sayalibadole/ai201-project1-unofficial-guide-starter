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
250–350 tokens per chunk (target ~300 tokens)
**Overlap:**
50 tokens overlap
**Why these choices fit your documents:**
Our corpus consists primarily of:

Student course reviews
Reddit comments and discussion threads
RateMyProfessor reviews
Course writeups and blog posts
UIUCMCS reviews

Most reviews are relatively short (1–5 paragraphs) and contain a single opinion or experience about workload, difficulty, projects, grading, or teaching quality. Because the documents are opinion-based rather than long technical manuals, very large chunks would combine multiple unrelated ideas and reduce retrieval precision.

A chunk size of approximately 300 tokens is large enough to preserve the context of a student's review while remaining focused on a specific experience. For example, a review discussing workload, project difficulty, and instructor quality can usually fit within a single chunk, allowing the retrieval system to return a coherent opinion rather than fragmented sentences.

A 50-token overlap helps preserve information that may span chunk boundaries. For example, a reviewer might describe project difficulty at the end of one chunk and explain its impact on workload at the beginning of the next. The overlap ensures that important context is not lost and that either chunk remains retrievable.

**Final chunk count:**
3,000–6,000 chunks
---

## Embedding Model

<!-- Name the embedding model you used and explain your choice.
     Then answer: if you were deploying this system for real users and cost wasn't a constraint,
     what tradeoffs would you weigh in choosing a different model?
     Consider: context length limits, multilingual support, accuracy on domain-specific text,
     latency, and local vs. API-hosted. -->

**Model used:**

**Production tradeoff reflection:**

---

## Grounded Generation

<!-- Explain how your system enforces grounding — how does it prevent the LLM from answering
     beyond the retrieved documents?
     Describe both your system prompt (what instruction you gave the model) and any structural
     choices (e.g., how you formatted the context, whether you filtered low-relevance chunks).
     Do not just say "I told it to use the documents" — show the actual instruction or explain
     the mechanism. -->

**System prompt grounding instruction:**

**How source attribution is surfaced in the response:**

---

## Evaluation Report

<!-- Run your 5 test questions from planning.md through your system and record the results.
     Be honest — a partially accurate or inaccurate result that you explain well is more
     valuable than a suspiciously perfect result. -->

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |

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

**What the system returned:**

**Root cause (tied to a specific pipeline stage):**

**What you would change to fix it:**

---

## Spec Reflection

<!-- Reflect on how planning.md shaped your implementation.
     Answer both questions with at least 2–3 sentences each. -->

**One way the spec helped you during implementation:**

**One way your implementation diverged from the spec, and why:**

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

- *What I gave the AI:*
- *What it produced:*
- *What I changed or overrode:*

**Instance 2**

- *What I gave the AI:*
- *What it produced:*
- *What I changed or overrode:*

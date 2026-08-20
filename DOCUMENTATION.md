# UniRAG — Complete Project Documentation

This document explains **what this project is, how it actually works end to end, and why each technology was chosen** — including the trade-offs against alternatives. It reflects the code as it currently exists in the repository (not the original README, which describes an earlier, simpler version of this same project — see [§10 Evolution](#10-evolution-how-this-diverged-from-the-readme) for what changed).

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [The big picture: two independent pipelines](#2-the-big-picture-two-independent-pipelines)
3. [Technology stack, and why each piece was chosen](#3-technology-stack-and-why-each-piece-was-chosen)
4. [Deep dive: the ingestion pipeline (offline)](#4-deep-dive-the-ingestion-pipeline-offline)
5. [Deep dive: the chat pipeline (online)](#5-deep-dive-the-chat-pipeline-online)
6. [Data model: what's actually stored, and where](#6-data-model-whats-actually-stored-and-where)
7. [API layer](#7-api-layer)
8. [Frontend](#8-frontend)
9. [Deployment / infrastructure](#9-deployment--infrastructure)
10. [Evolution: how this diverged from the README](#10-evolution-how-this-diverged-from-the-readme)
11. [Known gaps and inconsistencies (as of this writing)](#11-known-gaps-and-inconsistencies-as-of-this-writing)

---

## 1. What this project is

**UniRAG** is a chatbot that answers questions about Bangladeshi university admissions (GPA requirements, programs, fees, scholarships) by retrieving facts from a knowledge base built out of PDFs and scraped university websites, then having an LLM answer *only* from what it actually finds — instead of guessing.

It has two moving parts that barely touch each other:

- **A background job** that keeps the knowledge base fresh: scrape/read sources → detect what changed → chunk → embed → store as vectors.
- **A web app** that answers a user's message: classify the message → if it's a real question, search the vector store for relevant chunks → generate an answer grounded in those chunks.

The architecture is intentionally generic — it's not hardcoded to universities anywhere except in the prompt wording. Swap the PDFs, the URL list, and the prompt copy, and it becomes a knowledge assistant for anything else.

---

## 2. The big picture: two independent pipelines

```
                                   ┌───────────────────────────────────┐
                                   │        SHARED STORAGE LAYER        │
                                   │   ChromaDB collection "knowledge_  │
                                   │   chunks" — chroma_store/ on disk  │
                                   └───────────────┬─────────┬─────────┘
                                                   │         │
                        writes vectors             │         │  reads vectors
                        (never talks to the LLM)   │         │  (never scrapes)
                                                   │         │
┌──────────────────────────────────────┐           │         │           ┌──────────────────────────────────────┐
│         INGESTION PIPELINE            │◀──────────┘         └──────────▶│           CHAT PIPELINE                │
│         (offline, scheduled)          │                                 │         (online, per-request)          │
│                                        │                                 │                                        │
│  Celery Beat (daily 3AM Asia/Dhaka)    │                                 │  POST /chat/  (Django + DRF)           │
│        │                              │                                 │        │                              │
│        ▼                              │                                 │        ▼                              │
│  Celery worker runs                   │                                 │  LangGraph state machine               │
│  refresh_knowledge_base()             │                                 │        │                              │
│        │                              │                                 │        ▼                              │
│  ┌──────────────┬──────────────┐      │                                 │  classify_intent (Groq LLM call)       │
│  │ Web Loader    │ PDF Loader    │      │                                 │        │                              │
│  │ requests+bs4  │ PyMuPDF       │      │                                 │   ┌────┴────┐                        │
│  └──────┬───────┴──────┬───────┘      │                                 │   ▼         ▼                        │
│         │              │              │                                 │ CHITCHAT   KNOWLEDGE                 │
│         ▼              ▼              │                                 │   │         │                        │
│    SHA-256 content hash check          │                                 │   │    multi-query expansion (Groq)  │
│         │ (unchanged → skip)           │                                 │   │         │                        │
│         ▼                              │                                 │   │    parallel similarity search    │
│  RecursiveCharacterTextSplitter        │                                 │   │    (ChromaDB, one query per       │
│  (800 chars / 120 overlap)             │                                 │   │     variation)                    │
│         │                              │                                 │   │         │                        │
│         ▼                              │                                 │   │    merge + dedupe + threshold    │
│  sentence-transformers                 │                                 │   │    filter (min similarity 0.3)   │
│  all-MiniLM-L6-v2 (local, 384-dim)     │                                 │   │         │                        │
│         │                              │                                 │   │    answer generation (Groq,      │
│         ▼                              │                                 │   │    grounded in retrieved text)   │
│  ChromaDB upsert                       │                                 │   │         │                        │
│  (stable id per source+chunk_index)    │                                 │   └────┬────┘                        │
│                                        │                                 │        ▼                              │
└──────────────────────────────────────┘                                 │  update session memory + running      │
                                                                          │  summary (Groq)                       │
                                                                          │        ▼                              │
                                                                          │  JSON response to browser              │
                                                                          └──────────────────────────────────────┘
```

**Why keep these separate at all?** The chat path has to be fast (a user is waiting) and cheap (it runs on every message). The ingestion path can be slow and heavy (it runs once a day, in the background, with no one waiting on it). Mixing them — e.g. scraping a website live while a user waits for a chat reply — would make the chat path slow, flaky, and dependent on external websites being up at the exact moment someone asks a question. Splitting them means the *only* thing they share is the ChromaDB folder on disk.

---

## 3. Technology stack, and why each piece was chosen

### 3.1 Full stack at a glance

| Layer | Technology | Runs where | Needs API key? |
|---|---|---|---|
| Web framework | Django + Django REST Framework | local process | No |
| Task queue / scheduler | Celery + Celery Beat | local process | No |
| Message broker | Redis | container/local | No |
| Vector database | ChromaDB (`PersistentClient`) | local disk (SQLite + HNSW files) | No |
| Text chunking | LangChain `RecursiveCharacterTextSplitter` | local, in-process | No |
| Embedding model | `sentence-transformers` / `all-MiniLM-L6-v2` | local CPU | No |
| Web scraping | `requests` + `BeautifulSoup4` | local process | No |
| PDF parsing | PyMuPDF (`fitz`) | local process | No |
| DOCX parsing (uploads) | `python-docx` | local process | No |
| Image handling (uploads) | Pillow (`PIL`) | local process | No |
| Chat orchestration | LangGraph (`StateGraph`) | local, in-process | No |
| Chat LLM + vision + summarization | Groq API (`langchain-groq`) | Groq's cloud | **Yes** — `GROQ_API_KEY` |
| Frontend | Vanilla HTML/CSS/JS + `marked.js` (CDN) + Web Speech API | browser | No |

The one-line summary: **everything that touches your own documents runs locally and for free; the only thing that costs money or needs a key is the part that actually talks to a person.**

### 3.2 Why a vector database at all (using ChromaDB as the running example, as requested)

**The underlying problem it solves:** an LLM like the ones behind Groq doesn't know anything about a specific university's 2026 GPA cutoff unless that fact is put directly into its prompt. It also cannot hold every PDF and every scraped web page in its context window — that would be too much text, too expensive, and mostly irrelevant to any single question. So before answering, the system needs to find *just the handful of paragraphs that are actually relevant* to what the user asked, out of potentially thousands of chunks across 11+ PDFs and 100+ web sources.

A traditional (relational or keyword) database is good at exact matches and structured filters — `WHERE university = 'BUET'` — but a real user question like *"what GPA do I need for BUET's CSE program?"* doesn't map cleanly onto exact keyword matches against source text, especially once you consider synonyms, phrasing differences, and follow-up questions like *"what about fees?"* that only make sense with conversational context.

A **vector database** solves this by:
1. Converting every chunk of text into a fixed-length numeric vector (an *embedding*) that captures its meaning — texts with similar meaning end up as vectors that are numerically close together.
2. Converting the user's question into a vector the same way.
3. Finding the stored vectors that are closest to the question's vector (nearest-neighbor search) — which corresponds to "chunks that mean something similar to this question," not "chunks that share exact words."

This is what makes Retrieval-Augmented Generation (RAG) — the "R" in this whole system — possible at all: **retrieve by meaning, then let the LLM write the answer using only what was retrieved.**

**Why ChromaDB specifically, instead of Pinecone / Weaviate / Milvus / pgvector / FAISS:**

| Requirement | How ChromaDB meets it | What the alternative would have cost |
|---|---|---|
| No server to run/manage | `chromadb.PersistentClient` is a Python library that writes a SQLite file + HNSW index files straight to a local folder (`chroma_store/`) | Pinecone/Weaviate are hosted services — network calls, accounts, API keys, and often a paid tier. pgvector needs a running, configured, backed-up Postgres server. |
| Fits a single, self-contained knowledge base | One collection (`knowledge_chunks`), one process, one disk folder | Distributed vector DBs (Milvus, etc.) are built for scale this project doesn't have — many tenants, huge concurrent write volume |
| Zero cost, zero external dependency | Runs fully offline once the embedding model is downloaded once | Any hosted vector DB adds a recurring cost and an internet dependency even for local development |
| Metadata filtering alongside vector search | `collection.get(where={"source_ref": ...})` and `collection.delete(where=...)` combine exact filters with the vector index in one call — used for change detection and re-ingestion | A pure vector index (raw FAISS) has no built-in metadata store; you'd have to bolt on your own bookkeeping table |
| Plays well with the rest of the stack | Simple Python API, integrates naturally alongside LangChain/LangGraph, which are already used elsewhere here | N/A |

**The honest trade-off** (this project's own code comments call this out directly in `rag/vectorstore.py`): ChromaDB-as-an-embedded-library is a great fit for *one* knowledge base serving requests from *one* app instance. If this ever needed to serve many independent, large knowledge bases under heavy concurrent write load, or needed the vector store to scale as its own independent service, that's the point where a dedicated vector database server (Chroma's server mode, or something like Milvus/Weaviate/pgvector) would be worth revisiting. At this project's actual scale — a university admissions knowledge base, one collection, daily batch refreshes — that complexity isn't needed yet.

Each chunk's ID in Chroma is derived deterministically from `(source_ref, chunk_index)` (`rag/vectorstore.py::_chunk_id`), so re-ingesting the same source **overwrites** its old chunks instead of duplicating them — this is what makes "just run ingestion again" safe to do as often as you like.

### 3.3 Why local embeddings (`sentence-transformers`, `all-MiniLM-L6-v2`) instead of an embedding API

- **No API key, no rate limit, no per-embedding cost.** Ingesting 11 PDFs plus recursive crawls of 100+ university domains produces a *lot* of chunks. Doing that against a metered embedding API (the project's own comments mention this replaced an earlier Gemini-based embedding setup) meant hitting free-tier rate limits mid-run. A local model has no such ceiling.
- **`all-MiniLM-L6-v2` specifically**: small (~90MB), runs acceptably fast on plain CPU (no GPU required), and outputs a compact 384-dimensional vector — small enough for fast nearest-neighbor search, while still being a well-regarded general-purpose sentence embedding model.
- **One-time cost, then fully offline**: the model downloads from Hugging Face the first time it's used; every run after that needs no internet access at all for embeddings.
- **The constraint this creates**: embedding dimension is baked into the ChromaDB collection the first time vectors are written. Swapping to a different embedding model with a different output size requires wiping `chroma_store/` and re-embedding everything from scratch — you cannot mix vectors of different dimensions in one collection.

### 3.4 Why `RecursiveCharacterTextSplitter` for chunking (800 chars / 120 overlap)

Chunking exists because a whole PDF or web page is too big and too topically mixed to embed as a single vector (embedding the whole page would blur ten different facts into one vague vector that doesn't closely match any specific question) and too big to hand entirely to the LLM as context on every single question.

`RecursiveCharacterTextSplitter` tries to split on paragraph breaks first, then line breaks, then sentence-ending punctuation, then words — only falling back to a hard character cut as a last resort (`ingestion/chunker.py`). This keeps chunks readable and topically coherent rather than cutting a sentence in half arbitrarily.

- **800 characters**: small enough that one chunk usually stays about one topic (better retrieval precision — a chunk covering three unrelated facts will match badly against any specific question).
- **120 character overlap**: prevents a sentence that spans a chunk boundary from losing its meaning in both halves.
- **Fully local, no API calls** — this step costs nothing regardless of how much content there is.

### 3.5 Why LangGraph for chat orchestration, instead of plain if/else

The chat flow — classify the message, then branch into "chitchat" or "knowledge," each producing an answer — *could* be written as a function with an if-statement. LangGraph (`rag/router.py::build_graph`) instead expresses it as an explicit state machine: a typed `ChatState` (session id, query, intent, context, answer, history, summary, optional attached file) flows through named nodes (`classify`, `chitchat`, `knowledge`) connected by declared edges.

Why that's worth the extra structure here:
- **The state is typed and explicit** (`TypedDict`), so every node's inputs/outputs are visible in one place instead of scattered across nested conditionals.
- **Branches are declared, not nested** — adding a third branch (e.g., a dedicated "attached file" node instead of handling it inline inside `handle_knowledge`) is a graph edge, not a deeper if/else pyramid.
- **It's the natural fit alongside LangChain**, which the project already uses for chunking and the Groq LLM wrapper — same ecosystem, same mental model.

### 3.6 Why Groq for the LLM, and why a fallback model list

**Why Groq:** Groq runs open models (Llama, `gpt-oss`, Mixtral) on custom inference hardware (LPUs) that's dramatically faster than typical GPU-hosted inference, has a genuinely usable free tier, and integrates through `langchain-groq` with the same `ChatGroq` interface used throughout this codebase. Speed specifically matters here because a single user message can trigger *multiple* sequential LLM calls (intent classification → multi-query expansion → answer generation → background summary update) — a slower provider would make every chat turn noticeably sluggish.

**Why a fallback list, not just one model** (`rag/router.py::FALLBACK_MODELS`, `invoke_llm_with_fallback`): production LLM APIs occasionally return rate-limit (429) or transient errors, especially on a free tier. Rather than surfacing that as a hard failure to the user, the code tries the configured `GROQ_MODEL` first, then falls through `llama-3.3-70b-versatile` → `llama-3.1-8b-instant` → `mixtral-8x7b-32768` until one responds. This trades a small chance of a lower-quality answer for a much lower chance of the chat breaking outright.

**Why this needs an API key when nothing else in the pipeline does:** it's the one component that can't run "for free, locally, forever" — generating fluent, context-aware natural language responses (and describing images, and classifying intent) requires a capable general-purpose LLM, which isn't something a lightweight local model can substitute for at the same quality. Everything upstream of it (scraping, chunking, embedding, storage) was deliberately kept local specifically so that this is the *only* paid/keyed dependency in the whole system.

### 3.7 Why Celery + Redis for scheduling, instead of a cron job

- **Celery Beat** acts as the scheduler (`config/celery.py`), configured declaratively in Python (`crontab(hour=3, minute=0)`) alongside the rest of the Django settings — rather than an OS-level cron entry that lives outside the codebase and isn't version-controlled.
- **Redis** is the broker connecting three separate processes — the `beat` scheduler, the `worker` that actually executes the task, and (implicitly) the `web` process, all running in separate containers (`docker-compose.yml`) — so scheduling doesn't have to live inside the same process that's serving chat requests.
- **Why this matters for the chat path**: because ingestion runs in its own worker process on its own schedule, a slow scrape or a large re-embed never blocks or slows down a user's chat request. The two pipelines described in §2 are only able to stay this cleanly separated because Celery/Redis exists to run one of them independently in the background.

### 3.8 Why `requests` + BeautifulSoup for web scraping (and where Playwright fits in)

Most university websites in the source list serve their real content as static, server-rendered HTML — `requests` fetches the raw HTML and BeautifulSoup extracts and cleans the text (stripping `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>` tags that would otherwise pollute the extracted text with menu links and boilerplate). This is the cheapest possible way to scrape a page: one HTTP request, no browser to launch, no JavaScript engine to run.

**The known limitation**: if a page's actual content is injected by client-side JavaScript after load, `requests` only ever sees the near-empty HTML shell sent before any script runs. `playwright` (a full browser-automation library) is already listed in `requirements.txt` for exactly this situation, but **it is not currently wired into `web_loader.py`** — it's a deliberate "add it for the specific pages that need it" placeholder rather than a blanket switch, because launching a real browser per page is far heavier (memory, time, complexity) than a plain HTTP request, and most sources here don't need it.

The web loader also does a small amount of **recursive crawling**: starting from each seed URL, it looks at the page's links, keeps only same-domain links whose URL or link text contains an admissions-relevant keyword (`admission`, `tuition`, `scholarship`, `faculty`, etc. — see `KEYWORDS` in `ingestion/loaders/web_loader.py`), and crawls up to a few of those per domain. This is a targeted crawl, not a full-site crawl — it's trying to automatically find the 2-3 most relevant sub-pages per university without needing every single URL hand-listed in `web_sources.txt`.

### 3.9 Why PyMuPDF (`fitz`) for PDFs

PyMuPDF is used in two places: bulk ingestion of the reference PDFs in `knowledge_base/pdfs/` (`ingestion/loaders/pdf_loader.py`), and on-demand parsing of PDFs a user attaches in the chat UI (`rag/file_processor.py`). It's a fast, dependency-light C-library-backed PDF reader that extracts text page by page without needing an external binary (unlike, say, shelling out to `pdftotext`), and it's also used to **render a PDF page as an image** (`page.get_pixmap()`) — which is what makes the OCR fallback for scanned PDFs possible (see §3.10).

### 3.10 Why file/image upload gets its own path (`rag/file_processor.py`) and vision-model OCR

Beyond the main knowledge base, the chat UI lets a user attach a file (PDF, DOCX, TXT, or an image) directly to a message and ask about *that specific document*, without it needing to already be part of the crawled/indexed knowledge base. This is a deliberately separate path from retrieval:

- **PDF/TXT/DOCX** → parsed directly to text (PyMuPDF / `python-docx` / plain decode).
- **A scanned PDF with little to no extractable text** → falls back to rendering each page as an image and running it through a Groq **vision** model (`llama-3.2-11b-vision-preview` and similar) to get a description/transcription — this is OCR performed *by an LLM* rather than a dedicated OCR engine like Tesseract, chosen because the project already has a working relationship with Groq's chat models and a vision-capable model handles both "read the text" and "describe what's in the image" in one call.
- **A photo/image attachment** → goes through the same vision-model path directly.
- Before answering from an attached file, a relevance check LLM call filters out obviously off-topic attachments (recipes, unrelated documents) so the bot doesn't answer questions about content that has nothing to do with its university-admissions domain.

This whole path is independent of the vector store — it never touches ChromaDB. It's closer to "let the LLM read this one document you just handed it" than to retrieval-augmented generation.

### 3.11 Why the frontend is plain HTML/CSS/JS (no React/Vue framework)

`templates/chat.html` is a single Django template with vanilla JavaScript — no build step, no bundler, no framework. For a single chat page with a form, a message list, and a status indicator, a framework's state-management machinery wouldn't buy much; plain JS keeps it inspectable in one file and removes an entire build toolchain from the project. It pulls in exactly two external pieces at runtime: `marked.js` from a CDN to render the LLM's Markdown-formatted answers (bold text, headings, tables) as real HTML, and the browser's built-in **Web Speech API** for optional voice input — both are additive, and the page degrades gracefully (voice input button disables itself) if a browser doesn't support the Speech API.

---

## 4. Deep dive: the ingestion pipeline (offline)

Entry point: `ingestion/pipeline.py::run_ingestion()`, triggered by `ingestion/tasks.py::refresh_knowledge_base` (a Celery `shared_task`), which Celery Beat fires daily at 3:00 AM Asia/Dhaka (`config/celery.py`). It can also be run manually at any time — see the README's quick-start commands — and content hashing (§4.3) makes doing so repeatedly cheap.

**Step-by-step:**

1. **Read the source list.** `read_source_list()` reads `knowledge_base/web_sources.txt` line by line, skips blank lines and `#` comments, and normalizes bare domains (`www.example.edu.bd`) into full URLs by prepending `https://`.
2. **(Currently) clear the whole knowledge base first.** `run_ingestion()` is called with `reset_kb=True` by default, which wipes the entire ChromaDB collection (`clear_all_chunks()`) before re-ingesting everything from scratch on every run — see [§11](#11-known-gaps-and-inconsistencies-as-of-this-writing) for why this currently bypasses the per-source change-detection path described below on every scheduled run.
3. **Web loader** (`ingestion/loaders/web_loader.py::load_web_sources`) fetches each seed URL, strips it down to clean text with BeautifulSoup, and additionally crawls a handful of same-domain, keyword-matched sub-pages per seed (see §3.8). Each fetch is wrapped in its own `try/except` — one dead domain or timeout logs a failure and the loop moves on to the next source, so nine working sources still refresh even if a tenth is unreachable.
4. **PDF loader** (`ingestion/loaders/pdf_loader.py::load_pdf_sources`) reads every `.pdf` file in `PDF_SOURCE_DIR`, extracting all page text via PyMuPDF. Same failure-isolation pattern — a corrupt PDF is skipped, not fatal.
5. **Content hashing.** Every loaded document gets a SHA-256 hash of its extracted text (`content_hash`). When re-ingestion isn't doing a full reset, `source_unchanged()` (`rag/vectorstore.py`) checks this hash against what's already stored for that `source_ref` and skips re-processing entirely if nothing changed — this is what makes "run ingestion daily, or manually, as often as you like" safe and cheap rather than something that duplicates content or burns embedding time on unchanged pages every time.
6. **Purge stale chunks for that source.** `delete_chunks_for_source()` removes any previously stored chunks for that exact `source_ref` before inserting the refreshed version, so a page that shrank doesn't leave orphaned old chunks behind.
7. **Chunk.** `chunk_document()` (§3.4) splits the raw text into ~800-character overlapping pieces, tagging each with its source metadata and position index.
8. **Embed.** `embed_texts()` (§3.3) turns each chunk's text into a 384-dim vector, locally, in batch.
9. **Upsert into ChromaDB.** `upsert_chunks()` writes chunks in batches of 50 (to avoid ChromaDB compaction issues on very large documents), storing the vector, the raw chunk text, and metadata (`source_type`, `source_ref`, `title`, `content_hash`, `chunk_index`, `updated_at`) per chunk.
10. **Freshness becomes queryable data.** Because every chunk carries an `updated_at` timestamp, `/status/` can report "when did the knowledge base last change" and "how many distinct sources are indexed" without any separate bookkeeping table — this is what powers the "Shelves stamped..." indicator in the chat UI (§8). A knowledge base that refreshes itself silently is easy to stop trusting; surfacing *when* it last updated is what keeps that trust.

### 4.1 The three standalone scripts at the project root

`ingest_priority.py`, `ingest_remaining_pdfs.py`, and `inject_knowledge.py` are **not** part of the scheduled pipeline — they're one-off manual recovery/patch scripts, run directly (`python ingest_priority.py`), written for specific real incidents while building out this knowledge base:

- **`ingest_priority.py`** — re-scrapes a hardcoded list of Daffodil International University and North South University sub-pages directly (bypassing the source-list file), for when those two universities needed guaranteed indexing outside the normal crawl.
- **`ingest_remaining_pdfs.py`** — indexes a hardcoded list of six specific PDFs, written to resume ingestion after a crash that happened partway through the PDF loop (the comment literally says "crashed after BUP.pdf").
- **`inject_knowledge.py`** — hand-written, structured factual text for DIU and NSU (enrollment figures, faculties, rankings, contact info) inserted directly into ChromaDB, bypassing the loader/scraper entirely. This exists because DIU's and NSU's real websites are JavaScript-heavy and the current `requests`-based scraper can't extract their content (§3.8) — so instead of waiting on a Playwright-based loader, someone manually curated the key facts as text and injected them the same way any other chunk would be embedded and stored.

These are useful evidence of real operational hiccups during this project's development, but they're maintenance debt: none of them participate in the scheduled refresh, so if DIU's or NSU's real content ever needs updating, someone has to remember to re-run (and hand-edit) these scripts specifically.

---

## 5. Deep dive: the chat pipeline (online)

Entry point: `POST /chat/` → `api/views.py::chat` → `rag/router.py::chat_graph.invoke(...)`.

### 5.1 Request handling and file extraction

The view accepts either a plain JSON `{"message": "..."}` body or multipart form data with an optional `file` upload plus a `session_id` (defaulting to `"default"` if not supplied by the client). If a file is attached, `extract_text_from_file()` (§3.10) runs synchronously, right here in the request, before the LangGraph invocation even starts — so a large scanned PDF requiring vision-model OCR will make that single request slower (it's not backgrounded via Celery).

### 5.2 Session memory (`rag/memory.py`)

Before classification happens, the graph loads two things for the current `session_id` from an **in-process Python dictionary** (`_memory_store`, guarded by a `threading.Lock`):
- **Recent chat history** — the last few raw user/assistant turns, formatted as plain text (`format_history_text`).
- **A running summary** — a 2-3 sentence LLM-generated summary of "what's been discussed" (which universities, which topics, which answers were given), regenerated after every turn (`_update_summary`).

**Why a summary in addition to raw history, not just raw history**: raw history grows unboundedly and would eventually blow past what's reasonable to stuff into every subsequent prompt. A periodically-refreshed short summary keeps every downstream prompt (classification, query expansion, final answer) lightweight regardless of how long the conversation has run, while the last few raw turns still provide verbatim recent detail.

**Why in-memory rather than a database table or Redis**: simplest possible implementation for a single-process deployment — no schema, no migration, no extra I/O per turn. **The explicit trade-off**: this memory is lost on every process restart, and won't work correctly if the Django app is ever scaled to multiple worker processes/replicas (each would have its own separate, inconsistent memory dictionary) — since Redis is already part of this stack for Celery, that would be the natural place to move session memory if/when the app needs to run as more than one process.

### 5.3 Intent classification

`classify_intent` sends one Groq LLM call classifying the message as `CHITCHAT` or `KNOWLEDGE`, given the conversation summary/history as context — this is specifically so that a follow-up like *"what are the fees?"* right after a question about BUET gets correctly classified as `KNOWLEDGE` even though, in isolation, it looks like it could be either. If a file is attached, the intent is force-set to `KNOWLEDGE` without an LLM call, since an attached file always implies the user wants it processed.

### 5.4 The knowledge branch: multi-query retrieval

If a file is attached, `handle_knowledge` first tries to answer from the file directly (relevance check → answer, §3.10) before ever touching the vector store. Otherwise (or if the file's extracted text is just a filename-based fallback description), it calls `retrieve_context()` (`rag/retriever.py`):

1. **Query expansion** (`generate_query_variations`): one Groq call asks the LLM to generate 3 alternative phrasings of the user's question, explicitly resolving pronouns/abbreviations using the conversation summary/history — e.g. turning *"what about fees?"* into something like *"What are the tuition fees for North South University's CSE program?"*. If Groq is unavailable, this degrades gracefully to just the original query.
2. **Parallel-in-spirit similarity search**: each query variation (including the original) is embedded and searched against ChromaDB independently, top 8 results each.
3. **Merge + deduplicate**: all results across every query variation are merged into one dictionary keyed by `(source_ref, text)` — if the same chunk was found by more than one query variation, only its **highest** similarity score is kept.
4. **Similarity threshold filter (0.3)**: anything below this cosine-similarity cutoff is dropped before ever reaching the LLM — this is the mechanism that lets the bot honestly say "no information was found" instead of stretching to answer from weakly-related content.
5. **Final top-k selection + formatting**: the remaining chunks are sorted by score, the top 8 are kept, and formatted into labeled context blocks (`[title]\nSource: ...\n...`) joined together as the `context` the answer-generation prompt receives.

**Why go through all this instead of one plain similarity search on the raw query**: real conversational questions are often short, use abbreviations, or depend on prior turns for meaning. A single literal-similarity search on *"what about fees?"* alone would retrieve poorly, because that sentence alone doesn't carry the "North South University CSE" context needed to match the right chunks. Expanding into several resolved variations and merging their results casts a wider, better-aimed net at the cost of a few extra (fast, cheap) LLM and vector-search calls per message.

### 5.5 Answer generation

The final prompt instructs the LLM to match its answer's shape to the question's shape — a direct, short answer for a specific factual question ("where is BRAC University located?"), versus a structured, headed answer for a broad request ("tell me about BUET") — and to bold key facts, and to only claim "no information" if the retrieved context is actually empty of anything relevant. If retrieval returned nothing above the similarity threshold, the graph short-circuits straight to `"No information was found."` without spending an LLM call on it.

### 5.6 Chitchat branch

Much simpler: the raw message (plus the running summary, if one exists, for continuity) goes straight to the LLM at a higher temperature (0.7, vs 0.3 for knowledge answers) — no retrieval involved at all.

### 5.7 After every turn

Both branches call `add_turn()`, which appends the turn to session history and kicks off a summary regeneration for that session (§5.2) — so the *next* message in the conversation has an up-to-date summary available during classification and query expansion.

---

## 6. Data model: what's actually stored, and where

There are exactly two persistent stores, and they store almost entirely different things:

| Store | What's in it | Created by |
|---|---|---|
| `db.sqlite3` | Django's own bookkeeping only — `django.contrib.auth`, `contenttypes`, migrations state. **No custom Django models exist in this project** (`api`, `ingestion`, and `rag` all have empty/no `models.py`) — this file is essentially unused by the app's actual logic. | `python manage.py migrate` |
| `chroma_store/` | The entire knowledge base: one collection (`knowledge_chunks`), each entry = one chunk's vector + its text (`documents`) + its metadata (`source_type`, `source_ref`, `title`, `content_hash`, `chunk_index`, `updated_at`) | `ingestion/pipeline.py` via `rag/vectorstore.py` |

Session memory (chat history + running summaries) is **not persisted at all** — it's an in-process dictionary that exists only for the lifetime of the running Django process (see §5.2's trade-off note).

---

## 7. API layer

Defined in `api/urls.py`, implemented in `api/views.py`.

| Endpoint | Method | Body | Response |
|---|---|---|---|
| `/chat/` | POST | `message` (text), optional `session_id`, optional `file` (multipart) | `{"answer": "...", "intent": "KNOWLEDGE" \| "CHITCHAT" \| "ATTACHED_FILE", "session_id": "..."}` |
| `/status/` | GET | — | `{"last_updated": "<ISO timestamp or null>", "source_count": <int>}` |

`intent` in the chat response tells the frontend where the answer came from — retrieved knowledge, plain conversation, or an attached file — which is what drives the little "from the shelves" / "chitchat" / "from attached file" tag shown under each bot reply.

---

## 8. Frontend

`templates/chat.html` — a single Django template, no separate frontend build. Notable pieces:

- **Session continuity**: on first load, JS generates a random `sess_<random>_<timestamp>` ID and stores it in `localStorage`, so refreshing the browser tab keeps the same conversation session (and thus the same server-side memory/summary) rather than starting fresh every time.
- **Markdown rendering**: bot answers are run through `marked.js` (loaded from a CDN) so headings, bold text, lists, and tables the LLM produces render as actual formatted HTML instead of raw Markdown syntax.
- **File attachment**: a hidden file input plus a small preview chip; submitting sends the file as multipart form data alongside the message.
- **Voice input**: uses the browser's native `SpeechRecognition` API (no external service) to transcribe speech into the message box; the mic button disables itself if the browser doesn't support it.
- **Freshness stamp**: calls `/status/` on page load and renders "Shelves stamped `<date>` · `<n>` sources" (or "Shelves empty" if nothing has been ingested yet) — a direct, visible readout of the ingestion pipeline's own metadata (§4, step 10).

---

## 9. Deployment / infrastructure

`docker-compose.yml` defines four services: `redis` (Celery broker), `web` (Django + the chat UI/API, port 8000), `worker` (executes Celery tasks, including `refresh_knowledge_base`), and `beat` (the scheduler that enqueues that task daily). `web`, `worker`, and `beat` all mount the same `knowledge_base/` and `chroma_store/` folders as bind mounts (not named Docker volumes) — so both the source files and the vector store are plain files on the host, editable without touching Docker at all, and nothing is lost by tearing containers down.

`Dockerfile` is a single-stage `python:3.11-slim` image with `build-essential` installed (needed to build native dependencies for PyMuPDF and the ML packages), `requirements.txt` installed, then the project copied in.

All runtime configuration is environment-driven via `.env` (loaded by `python-dotenv` in `config/settings.py`) — see the README's configuration reference table for the full list of variables (Groq key/model, Django secret/debug/hosts, Redis URL, source directories, Chroma persist directory).

---

## 10. Evolution: how this diverged from the README

The project's `README.md` documents an earlier, simpler shape of this same system — chitchat/knowledge routing, single-query retrieval at a fixed top-5/0.5-threshold, no session memory, no file uploads. The code has since grown substantially beyond that description without the README being updated to match:

- **Session memory + running summaries** (`rag/memory.py`) were added — conversations now have continuity across turns.
- **Multi-query retrieval** (`rag/retriever.py`) replaced single-query similarity search — top_k moved from 5 to 8, threshold moved from 0.5 to 0.3.
- **File/image upload with vision-model OCR fallback** (`rag/file_processor.py`) was added as an entirely separate answer path alongside retrieval.
- **Groq model fallback chain** (`rag/router.py::invoke_llm_with_fallback`) was added for resilience against rate limits.
- Code comments in `rag/vectorstore.py` and `ingestion/embedder.py` reference an **earlier Postgres + pgvector + Gemini-embeddings setup** that predates even the README's description — this project has been migrated at least twice: Postgres/pgvector/Gemini → (README's description) → the current ChromaDB/local-embeddings/multi-query/memory version documented here.

This document (`DOCUMENTATION.md`) describes the system **as the code currently behaves**; treat `README.md` as a still-useful quick-start guide for running the project, but not as an accurate architecture reference until it's updated.

---

## 11. Known gaps and inconsistencies (as of this writing)

Worth knowing about, not necessarily worth fixing immediately:

- **`run_ingestion()` defaults to `reset_kb=True`**, which wipes the *entire* ChromaDB collection before every run (`ingestion/pipeline.py`). This means the content-hash "skip unchanged sources" logic (§4, step 5) — while still present in the code and used by the standalone scripts — is currently bypassed on every scheduled/manual full run, since there's nothing left to compare against after a full wipe. Every scheduled 3 AM run currently re-scrapes, re-chunks, and re-embeds *everything*, rather than only what changed.
- **Missing dependencies for the file-upload path**: `rag/file_processor.py` imports `python-docx` (as `docx`) and `Pillow` (as `PIL`), but neither package is listed in `requirements.txt`. DOCX and image uploads will fail with an import error in an environment built strictly from `requirements.txt` as it currently stands.
- **`playwright` is installed but unused** — listed in `requirements.txt` and mentioned in comments as the intended fix for JavaScript-heavy sites, but `web_loader.py` has no Playwright-based code path yet. The JS-heavy-site problem was instead worked around manually via `inject_knowledge.py` (§4.1) for the two specific universities that needed it.
- **Session memory doesn't survive a restart or scale past one process** — see §5.2's trade-off note.
- **The three root-level scripts** (`ingest_priority.py`, `ingest_remaining_pdfs.py`, `inject_knowledge.py`) contain hardcoded source lists and hand-curated facts that will silently go stale — nothing re-runs them automatically, and their content isn't kept in sync with the live scraper.
- **File uploads run synchronously in the request/response cycle** — a large scanned PDF triggering the vision-model OCR fallback (§3.10) will make that one HTTP request slow, since it isn't offloaded to a Celery task the way scheduled ingestion is.

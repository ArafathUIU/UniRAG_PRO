# Reading Room — RAG Chatbot with a Self-Updating Knowledge Base

A chatbot that answers casual messages directly and routes factual questions
to a knowledge base built from your own PDFs and websites — refreshed
automatically on a schedule, with no manual re-indexing required day to day.

Originally built around university admission info for Bangladesh (SSC/HSC
GPA requirements, programs, etc.), but the architecture is generic — swap in
any PDFs or web pages and it works the same way.

---

## Table of contents

1. [What this project does](#1-what-this-project-does)
2. [Architecture](#2-architecture)
3. [Quick start — Docker (recommended)](#3-quick-start-docker-recommended)
4. [Quick start — without Docker](#4-quick-start-without-docker)
5. [Adding to the knowledge base](#5-adding-to-the-knowledge-base)
6. [Using the app](#6-using-the-app)
7. [Configuration reference](#7-configuration-reference)
8. [How each piece works](#8-how-each-piece-works)
9. [Project layout](#9-project-layout)
10. [Extending this project](#10-extending-this-project)
11. [Troubleshooting](#11-troubleshooting)
12. [Security notes](#12-security-notes)

---

## 1. What this project does

A visitor opens the chat page and types a message. Behind the scenes:

- **Small talk** ("hi", "how are you") gets answered directly by the LLM,
  no lookup involved.
- **Factual questions** ("what GPA do I need for BUET's CSE program?") get
  routed to a knowledge base search first — the chatbot answers only from
  what it actually finds there, and says so honestly if it finds nothing
  relevant, instead of guessing.

Separately, on a schedule (daily by default), a background job:

- Reads every PDF in `knowledge_base/pdfs/`
- Scrapes every URL listed in `knowledge_base/web_sources.txt`
- Skips anything unchanged since last time (via content hashing)
- Chunks, embeds (locally, no API), and stores new/changed content in ChromaDB

You never have to manually "re-index" — drop a file in, add a URL to a text
file, and the next scheduled run (or a manual trigger) picks it up.

**Everything runs locally except one thing: the chat LLM itself.** No
Postgres server, no pgvector, no Gemini — chunking, embedding, and vector
storage are all local; only generating the actual chat response calls out
to Groq's API.

---

## 2. Architecture

```
User Message
     │
     ▼
┌─────────────┐
│   Router     │  LangGraph node — classifies intent
│ (chitchat vs │
│  knowledge)  │
└──────┬───────┘
       │
   ┌───┴────┐
   ▼        ▼
CHITCHAT   KNOWLEDGE
   │        │
   │        ▼
   │   ┌─────────────┐
   │   │  Retriever   │──▶ ChromaDB similarity search (local, SQLite-backed)
   │   └──────┬───────┘
   │          ▼
   │   ┌─────────────┐
   │   │ LLM + Context│  Groq (openai/gpt-oss-20b)
   │   └──────┬───────┘
   ▼          ▼
      Response to user


Scheduled Job (Celery Beat — daily at 3 AM Asia/Dhaka by default)
     │
     ▼
┌──────────────────┐     ┌──────────────────┐
│  Web Loader        │     │  PDF Loader        │
│  reads              │     │  reads              │
│  web_sources.txt    │     │  knowledge_base/    │
│  (requests + bs4)   │     │  pdfs/ (PyMuPDF)    │
└─────────┬──────────┘     └─────────┬──────────┘
          │                          │
          └───────────┬──────────────┘
                       ▼
             ┌──────────────────┐
             │  Content Hash     │  skip unchanged content
             │  Check            │
             └────────┬──────────┘
                       ▼
             ┌──────────────────┐
             │  Chunker          │  RecursiveCharacterTextSplitter (local)
             └────────┬──────────┘
                       ▼
             ┌──────────────────┐
             │  Embedder         │  sentence-transformers, local, no API
             └────────┬──────────┘
                       ▼
             ┌──────────────────┐
             │  ChromaDB Upsert  │  persistent, SQLite-backed, local disk
             └──────────────────┘
```

The chat path and the ingestion path share nothing except the ChromaDB
collection on disk — the chatbot never scrapes on demand, and the ingestion
job never talks to the chat LLM. That separation keeps the scheduled
refresh cheap and the chat response fast.

**Three different technologies are used, for three different jobs:**

| Job | Technology | Needs an API key / server? |
|---|---|---|
| Turning text into chunks | `RecursiveCharacterTextSplitter` (LangChain) | No — pure local text splitting |
| Turning chunks into vectors (ingestion) | `all-MiniLM-L6-v2` (sentence-transformers) | No — runs locally on CPU |
| Storing and searching vectors | ChromaDB (persistent, SQLite-backed) | No — a local file, not a server |
| Classifying intent + generating chat answers | `openai/gpt-oss-20b` (Groq) | **Yes** — `GROQ_API_KEY` |

This matters in practice: you can run the entire ingestion pipeline —
scraping, chunking, embedding, storing — **with no API key set at all,
and no separate database server running.** The only thing that needs
`GROQ_API_KEY` is the part that actually talks to a user.

---

## 3. Quick start — Docker (recommended)

```bash
cp .env.example .env
# edit .env and set GROQ_API_KEY — get one free at https://console.groq.com/keys
# only needed for chat responses; ingestion works without it

# drop any PDFs you want indexed into ./knowledge_base/pdfs
# add web pages to scrape to ./knowledge_base/web_sources.txt (one URL per line)

docker compose up --build
```

Three containers start:

| Container | Role |
|---|---|
| `redis` | Celery broker |
| `web` | Django app — chat UI + API on `http://localhost:8000` |
| `worker` + `beat` | Celery worker and the scheduler (`config/celery.py`) |

There's no database container to wait on — Django's own bookkeeping uses a
plain SQLite file (`db.sqlite3`), and the knowledge base's vectors live in
`chroma_store/`, both created automatically on first run.

Run the scrape/ingest once immediately instead of waiting for the schedule:
```bash
docker compose exec web python manage.py shell -c "from ingestion.pipeline import run_ingestion; run_ingestion()"
```
You'll see output like:
```
[pipeline] refreshed 87 chunks for: /app/knowledge_base/pdfs/BUET.pdf
[pipeline] refreshed 12 chunks for: https://www.uiu.ac.bd/admission/admission-requirements/
[pipeline] unchanged, skipping: /app/knowledge_base/pdfs/DU.pdf
```

- **`http://localhost:8000/`** — the chat UI
- **`http://localhost:8000/chat/`** — POST-only JSON API (`{"message": "..."}`)
- **`http://localhost:8000/status/`** — GET, knowledge base freshness

Stop everything: `docker compose down`. There's no named Docker volume
anymore (unlike the old Postgres setup) — `chroma_store/` and `db.sqlite3`
are plain files bind-mounted from your project folder, so they persist
automatically and `docker compose down -v` has nothing left to wipe.

**On Windows**, if you re-extract an updated project zip over an existing
folder, use PowerShell's `Expand-Archive -Force` rather than right-click
"Extract All" — the latter can silently skip overwriting files it thinks
already exist:
```powershell
Expand-Archive -Path project.zip -DestinationPath . -Force
```
Then always rebuild before restarting containers when code has changed:
```powershell
docker compose down
docker compose build --no-cache
docker compose up
```

## 4. Quick start — without Docker

```bash
pip install -r requirements.txt

python manage.py migrate
celery -A config worker -l info
celery -A config beat -l info
python manage.py runserver
```

The first time ingestion runs, `sentence-transformers` downloads its
embedding model (~90MB) from Hugging Face — make sure you have internet
access for that one run. After that, embeddings work fully offline.
ChromaDB itself needs no separate install or server — it's a Python
package that writes to a local folder (`chroma_store/` by default).

---

## 5. Adding to the knowledge base

There are two source types, and both are designed to be edited without
touching any code:

### PDFs
Drop files into `knowledge_base/pdfs/`. That's it — the next ingestion run
(scheduled or manual) picks them up. Filenames become the document's
display title.

### Web pages
Edit `knowledge_base/web_sources.txt` — a plain text file:
```
# One URL per line. Lines starting with # are comments.
https://www.uiu.ac.bd/admission/admission-requirements/
https://www.uiu.ac.bd/admission/undergraduate-program/
```
Add or remove lines any time. No rebuild, no restart — `knowledge_base/` is
volume-mounted into every container, so the very next ingestion run reads
whatever is currently in the file.

**One limitation to know about:** the web loader (`ingestion/loaders/web_loader.py`)
only reads static, server-rendered HTML (via `requests` + BeautifulSoup). If
a page loads its real content via JavaScript, the scraper will see a
near-empty page. `playwright` is already in `requirements.txt` for exactly
this situation — it's just not wired into the loader yet. If you hit a page
that needs it, that's a scoped addition to `web_loader.py` for that specific
source, not a change to the whole pipeline (see [§10](#10-extending-this-project)).

### Re-running ingestion manually
```bash
docker compose exec web python manage.py shell -c "from ingestion.pipeline import run_ingestion; run_ingestion()"
```
Safe to run as often as you like — unchanged sources are skipped via content
hashing, so re-running costs almost nothing.

### Checking what's currently loaded
```bash
curl http://localhost:8000/status/
```
Returns the most recent update timestamp and how many distinct sources are
indexed — this is also what powers the "Shelves stamped..." line in the
chat UI.

---

## 6. Using the app

**Chat UI** — open `http://localhost:8000/` in a browser.

**JSON API directly:**
```bash
curl -X POST http://localhost:8000/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "What GPA do I need for BUET CSE?"}'
```
Response shape:
```json
{
  "answer": "...",
  "intent": "KNOWLEDGE"
}
```
`intent` is either `"KNOWLEDGE"` (answer came from the retrieved knowledge
base passages) or `"CHITCHAT"` (answered directly, no retrieval).

---

## 7. Configuration reference

All of this lives in `.env` (copy `.env.example` to start):

| Variable | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | *(required for chat)* | Get one free at [console.groq.com/keys](https://console.groq.com/keys). Used only by the chat LLM (`rag/router.py`) — not needed for ingestion. |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Groq's current recommended fast/cheap model. Use `openai/gpt-oss-120b` for higher quality at more cost. See [console.groq.com/docs/models](https://console.groq.com/docs/models) for the current list — Groq deprecates and replaces models periodically. |
| `DJANGO_SECRET_KEY` | `change-me-in-production` | Change before any real deployment |
| `DJANGO_DEBUG` | `True` | Set `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | Restrict in production |
| `REDIS_URL` | `redis://localhost:6379/0` (Docker overrides to `redis://redis:6379/0`) | Celery broker/result backend |
| `PDF_SOURCE_DIR` | `./knowledge_base/pdfs` | Folder scanned for PDFs |
| `WEB_SOURCES_FILE` | `<project>/knowledge_base/web_sources.txt` | Text file listing URLs to scrape |
| `CHROMA_PERSIST_DIR` | `<project>/chroma_store` | Folder where ChromaDB stores its SQLite file and index data |

No database credentials to configure — Django's own bookkeeping uses a
local `db.sqlite3` file, and the knowledge base lives in `CHROMA_PERSIST_DIR`.

Non-`.env` settings you might want to tune directly in code:

| What | Where |
|---|---|
| Refresh schedule (currently daily, 3 AM Asia/Dhaka) | `crontab(...)` in `config/celery.py` |
| Chunk size / overlap (currently 800 / 120 chars) | `ingestion/chunker.py` |
| Embedding model (currently `all-MiniLM-L6-v2`, 384-dim) | `ingestion/embedder.py` |
| Retrieval top-k / similarity threshold (currently 5 / 0.5) | `rag/retriever.py` |
| Chat LLM temperature (currently 0.3) | `rag/router.py` |

---

## 8. How each piece works

### 8.1 Storage: ChromaDB (persistent, SQLite-backed)
`rag/vectorstore.py` holds all the vector-store logic. `chromadb.PersistentClient`
writes to a local folder (`CHROMA_PERSIST_DIR`) — a SQLite file for
metadata plus HNSW index files for fast approximate nearest-neighbor
search. There's no separate database server to run, configure, or keep
healthy; it's just a Python library writing to disk, which is what makes
`docker-compose.yml` able to drop an entire container compared to a
Postgres+pgvector setup. This is a good fit for a single-purpose knowledge
store at the scale this project operates at (one knowledge base, not a
multi-tenant system serving many independent teams). If you ever needed
concurrent writes from many separate processes at high volume, or wanted
the vector store to live as its own scalable service independent of the
app, that's when a dedicated Chroma server (or a different vector database
entirely) would be worth revisiting — not a concern at this project's scale.

Each chunk gets a stable ID derived from `(source_ref, chunk_index)`, so
re-ingesting the same source overwrites its old chunks instead of
duplicating them.

### 8.2 Chunking strategy
`ingestion/chunker.py` uses `RecursiveCharacterTextSplitter` at **800
characters with 120 overlap**:
- Small enough that a chunk stays topically focused (better retrieval
  precision — you don't want one chunk covering three unrelated topics)
- Large enough to preserve context within a paragraph
- The overlap prevents a sentence that matters from being split exactly at
  a chunk boundary and losing meaning on both sides

Fully local — no API calls, no cost, no rate limits. Tune per source type
if needed; dense PDFs (policy documents, academic text) often benefit from
slightly larger chunks than short web pages.

### 8.3 Embedding model
`ingestion/embedder.py` runs **`all-MiniLM-L6-v2`** locally via
`sentence-transformers` — no API calls, no rate limits, no API key. The
first run downloads the model (~90MB) from Hugging Face; after that it's
fully offline. It outputs 384-dimension vectors.

If you swap to a different embedding model with a different output
dimension, update `EMBEDDING_DIM` in `ingestion/embedder.py`, then wipe and
re-embed everything — dimensions can't be mixed in one ChromaDB collection:
```bash
rm -rf chroma_store   # or: docker compose down && rm -rf chroma_store
docker compose up --build
docker compose exec web python manage.py shell -c "from ingestion.pipeline import run_ingestion; run_ingestion()"
```

### 8.4 Retrieval strategy
`rag/retriever.py` pulls the top 5 chunks by cosine similarity and applies
a **minimum similarity threshold (0.5)** before handing anything to the
LLM. This matters for a knowledge base that's honest about its limits: if
nothing in the store actually relates to the question, the bot says so
instead of the LLM improvising an answer from weak, barely-related context.
Tune the threshold once you see real query patterns — too high and you'll
get false "I don't know"s, too low and you'll get hallucination-prone weak
matches.

### 8.5 Routing: chitchat vs. knowledge
`rag/router.py` builds a small LangGraph with one classification node
(`classify_intent`) and two branches. A message is classified as
`CHITCHAT` or `KNOWLEDGE` by a single LLM call, then routed accordingly —
chitchat gets a direct response, knowledge gets retrieval-augmented. This
keeps the chatbot from trying to force every casual message through a
knowledge base search it doesn't need. The LLM for both classification and
generation is Groq's `openai/gpt-oss-20b` by default — fast and cheap,
which suits a two-call-per-message pattern (classify, then answer) well.

### 8.6 Freshness is a first-class piece of data
Every chunk carries `content_hash` and an `updated_at` timestamp in its
ChromaDB metadata. The `/status/` endpoint (`api/views.py`) surfaces the
most recent update time and the number of distinct sources indexed — this
is what powers the "shelves stamped" indicator in the chat UI. A knowledge
base that refreshes itself silently is easy to stop trusting; showing
*when* it last updated is what keeps that trust.

### 8.7 Content hashing makes "run it often" safe
Every source's `content_hash` is checked against what's already stored
(`source_unchanged()` in `rag/vectorstore.py`) before any chunking or
embedding work happens:
- **Unchanged** → skip entirely, zero cost
- **Changed** → delete that source's old chunks, re-chunk, re-embed, re-insert
- **New source** → chunk, embed, insert

This is the difference between a scraper that's safe to run daily (or
manually, repeatedly, while testing) and one that duplicates content and
burns embedding time every run.

### 8.8 Failure isolation
One dead link or a PDF that fails to parse should never take down the whole
run. Each loader wraps individual sources in `try`/`except` — a failure
logs and moves on, so nine working sources still refresh even if the tenth
is down.

### 8.9 Where sources are declared
- **Web URLs** → `knowledge_base/web_sources.txt` (see [§5](#5-adding-to-the-knowledge-base))
- **PDFs** → `knowledge_base/pdfs/` (`PDF_SOURCE_DIR`)

Both are plain files/folders, not scattered through Python — the goal is
that adding one more source is a non-technical edit, not a code change.

---

## 9. Project layout

```
rag-chatbot/
├── config/
│   ├── celery.py            # Celery app + refresh schedule
│   ├── settings.py           # Groq key, ChromaDB path, WEB_SOURCES_FILE, PDF_SOURCE_DIR
│   ├── urls.py               # / → chat UI, includes api.urls
│   └── wsgi.py
├── ingestion/
│   ├── loaders/
│   │   ├── web_loader.py      # scrapes URLs from web_sources.txt
│   │   └── pdf_loader.py      # reads PDFs from PDF_SOURCE_DIR
│   ├── chunker.py             # RecursiveCharacterTextSplitter (local)
│   ├── embedder.py            # sentence-transformers (local)
│   ├── pipeline.py            # loaders → hash check → chunk → embed → upsert
│   └── tasks.py               # Celery task, runs on schedule
├── rag/
│   ├── vectorstore.py         # ChromaDB collection + upsert/query/status helpers
│   ├── retriever.py           # similarity search + threshold filtering
│   └── router.py              # LangGraph: chitchat vs knowledge branch (Groq)
├── api/
│   ├── views.py               # /chat/ and /status/ endpoints
│   └── urls.py
├── templates/
│   └── chat.html               # chat UI (vanilla JS, no framework)
├── knowledge_base/
│   ├── pdfs/                   # drop PDFs here
│   └── web_sources.txt         # list of URLs to scrape, one per line
├── chroma_store/                # ChromaDB's persistent data (created on first run)
├── db.sqlite3                    # Django's own bookkeeping (created on first run)
├── docker-compose.yml            # redis, web, worker, beat services
├── Dockerfile
├── requirements.txt
├── .env.example
└── manage.py
```

---

## 10. Extending this project

- **New source type** (e.g. Notion, Confluence, Google Drive): write one
  loader emitting the shared document shape (`source_type`, `source_ref`,
  `title`, `raw_text`, `content_hash`), call it from `ingestion/pipeline.py`
  alongside the existing two. Everything downstream (chunking, embedding,
  storage) works off that shape unchanged.
- **JavaScript-rendered web sources**: add a Playwright-based loader
  (the dependency is already in `requirements.txt`) for just those specific
  URLs — don't switch the whole pipeline to Playwright, since it's much
  heavier per page than plain `requests`.
- **Different refresh cadence**: change the `crontab(...)` in
  `config/celery.py` — e.g. `crontab(hour="*/6")` for every 6 hours.
  Content hashing means running it more often costs you almost nothing on
  unchanged sources.
- **Answer quality**: if retrieval starts missing relevant chunks, first
  try widening `top_k` or lowering the similarity threshold in
  `rag/retriever.py` before changing the embedding model — cheaper to tune
  and diagnose.
- **Different Groq model**: change `GROQ_MODEL` in `.env` — e.g.
  `openai/gpt-oss-120b` for higher-quality responses at more cost per
  token. No code change needed.
- **Different embedding model**: see [§8.3](#83-embedding-model) — requires
  wiping `chroma_store/` and re-embedding everything.
- **Scaling the vector store beyond a single knowledge base**: if this
  ever needs to serve many independent, large knowledge bases with heavy
  concurrent write load, that's the point to evaluate a dedicated vector
  database service instead of the embedded ChromaDB setup here.

---

## 11. Troubleshooting

**Chat responses fail but ingestion works fine.**
Ingestion doesn't need `GROQ_API_KEY` at all — only the chat path does.
If chat is failing, check that `GROQ_API_KEY` is actually set in `.env`
and that the container picked it up (`docker compose exec web env | grep GROQ`).

**A Groq model ID stops working ("model not found" or similar).**
Groq periodically deprecates older models with advance notice. Check
[console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations)
for the current recommended replacement, then update `GROQ_MODEL` in `.env`
— no code change needed.

**A web source I added isn't showing any useful content.**
The page is likely rendered via JavaScript, which the current scraper
(`requests` + BeautifulSoup) can't execute. Check the raw HTML the page
sends before any JS runs — if the content you want isn't there, it needs a
Playwright-based loader instead (see [§10](#10-extending-this-project)).

**Ingestion errors after changing the embedding model.**
Existing vectors in `chroma_store/` were embedded at the old dimension and
are incompatible with a differently-sized model. Wipe and re-ingest — see
[§8.3](#83-embedding-model).

**Windows: files don't seem to update after re-extracting a zip.**
Right-click "Extract All" can silently skip files it thinks already exist.
Use `Expand-Archive -Force` in PowerShell instead (see [§3](#3-quick-start-docker-recommended)).

**Starting fresh / wiping the knowledge base entirely.**
Unlike the old Postgres setup, there's no named Docker volume to `-v` away.
Just stop the containers and delete the folder:
```bash
docker compose down
rm -rf chroma_store db.sqlite3
docker compose up --build
```

---

## 12. Security notes

- **Never commit a real `GROQ_API_KEY`** to `.env` or `.env.example` in
  version control or shared files — `.env` should stay out of git (see
  `.gitignore`) and `.env.example` should only ever contain a placeholder
  like `your-key-here`.
- If a real key is ever accidentally shared or committed, rotate/revoke it
  immediately in the [Groq console](https://console.groq.com/keys) and
  issue a new one.
- `DJANGO_SECRET_KEY` in `.env.example` is a placeholder — set a real value
  before any non-local deployment, and set `DJANGO_DEBUG=False` with a
  restricted `DJANGO_ALLOWED_HOSTS`.

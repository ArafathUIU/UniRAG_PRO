# UniRAG: Production Architecture & Complete Pipeline Specification

This document provides a detailed specification of the **UniRAG** system. It covers data layouts, component specifications, mathematical models, background scheduling mechanisms, and query execution graphs.

---

## 1. System Topology & Directory Mappings

The codebase is organized into modules with strict boundaries separating Django's REST layer, the Celery ingestion worker, the local ChromaDB database, and the LangGraph conversation pipeline.

```
rag-chatbot/
├── config/                  # Django project configuration & WSGI/ASGI entrypoints
│   ├── celery.py            # Celery App initialization and Beat schedules
│   ├── settings.py          # Environment loading and Django settings
│   └── urls.py              # Root routing table
├── api/                     # REST API application
│   ├── views.py             # Chat and Status REST view endpoints
│   └── urls.py              # Endpoint route definitions (/chat/, /status/)
├── ingestion/               # Background Scheduled Ingestion Pipeline
│   ├── loaders/             # Data loading utilities
│   │   ├── web_loader.py    # Recursive web crawler (requests + bs4)
│   │   └── pdf_loader.py    # PDF text loader (PyMuPDF)
│   ├── chunker.py           # Recursive text splitting logic
│   ├── embedder.py          # sentence-transformers embedding generation
│   ├── pipeline.py          # Main ingestion pipeline orchestrator
│   └── tasks.py             # Celery Shared Tasks definitions
├── rag/                     # Conversational retrieval and LLM logic
│   ├── memory.py            # Session storage and dynamic summary generator
│   ├── retriever.py         # Multi-query vector retriever & deduplicator
│   ├── router.py            # LangGraph routing and response generation graph
│   └── vectorstore.py       # ChromaDB wrapper client
├── knowledge_base/          # Knowledge base documents and source lists
│   ├── pdfs/                # Local PDF directory
│   └── web_sources.txt      # Text list of URLs to crawl
├── templates/               # Frontend templates
│   └── chat.html            # Conversational Chat UI
├── db.sqlite3               # Relational database for Django bookkeeping
└── chroma_store/            # Local vector database storage (SQLite-backed ChromaDB)
```

---

## 2. Ingestion Pipeline & Scheduled Tasks (Offline Flow)

```
[Celery Beat Trigger] ➔ [Redis Queue] ➔ [Celery Worker]
                                               │
 ┌─────────────────────────────────────────────┘
 │
 ▼ 1. Scrape / Load
 ├── Web Loader: Scrape root domain + crawl child pages
 └── PDF Loader: Read PDFs page-by-page using PyMuPDF
 │
 ▼ 2. Content Hashing (SHA-256)
 ├── Calculate hash of extracted text
 └── Compare with stored database hash ➔ Skip if identical
 │
 ▼ 3. Text Splitting & Chunking
 ├── Chunks: 1000 characters
 └── Overlap: 200 characters
 │
 ▼ 4. Purge Obsolete Data
 └── delete_chunks_for_source(source_ref)
 │
 ▼ 5. Generate Vector Embeddings
 ├── Batch size: 50 chunks
 └── Model: all-MiniLM-L6-v2 (384-dimensional dense vectors)
 │
 ▼ 6. ChromaDB Persist
 ├── Generates chunk IDs using hash of source_ref and chunk_index
 └── SQLite storage write + HNSW Hashing
```

### 2.1 Loader Module Workflows
* **PDF Loader (`ingestion/loaders/pdf_loader.py`)**:
  - Code reference: [pdf_loader.py](file:///c:/Users/Tarek/Desktop/rag-chatbot/ingestion/loaders/pdf_loader.py)
  - Scans `./knowledge_base/pdfs/` for `.pdf` files.
  - Extracts text layout page-by-page:
    ```python
    import fitz # PyMuPDF
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    ```
* **Web Loader (`ingestion/loaders/web_loader.py`)**:
  - Code reference: [web_loader.py](file:///c:/Users/Tarek/Desktop/rag-chatbot/ingestion/loaders/web_loader.py)
  - Loads a list of target domains from `knowledge_base/web_sources.txt`.
  - Performs depth-first recursive link crawling. Only parses child links that belong to the same parent domain.
  - Purges navigation bars, scripts, styles, and headers:
    ```python
    soup = BeautifulSoup(response.content, "html.parser")
    for element in soup(["script", "style", "nav", "header", "footer"]):
        element.decompose()
    clean_text = soup.get_text(separator="\n")
    ```

### 2.2 Content Hashing Verification
To avoid redundant embeds, the system calculates document checksums:
$$\text{Checksum} = \text{SHA256}(\text{Document String})$$
Before processing, it queries ChromaDB to check if the hash has changed:
```python
results = collection.get(where={"source_ref": source_ref}, limit=1, include=["metadatas"])
```
If a match is found and `results['metadatas'][0]['content_hash'] == current_hash`, indexing is skipped.

### 2.3 Recursive Splitting & Vector Generation
* **Chunking**: Uses `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)` to divide text into semantic segments.
* **Embeddings**:
  - Uses the `all-MiniLM-L6-v2` HuggingFace pipeline to map segments to **384-dimensional dense vectors**.
  - Normalized vector coordinates ensure that Cosine distance reflects semantic similarity:
    $$\text{Cosine Similarity}(A, B) = \frac{A \cdot B}{\|A\| \|B\|}$$
    Since embeddings are pre-normalized, this simplifies to:
    $$\text{Cosine Similarity}(A, B) = A \cdot B$$
    In ChromaDB (using `cosine` space metadata):
    $$\text{Chroma Distance} = 1 - \text{Cosine Similarity}$$

### 2.4 Celery Scheduler Configuration
Celery uses **Redis** as a broker and **Celery Beat** to schedule tasks:
* Task definitions: [tasks.py](file:///c:/Users/Tarek/Desktop/rag-chatbot/ingestion/tasks.py)
* Scheduler Configuration: [celery.py](file:///c:/Users/Tarek/Desktop/rag-chatbot/config/celery.py)
  ```python
  app.conf.beat_schedule = {
      "daily-knowledge-base-refresh": {
          "task": "ingestion.tasks.refresh_knowledge_base",
          "schedule": crontab(hour=3, minute=0), # 3:00 AM Asia/Dhaka
      },
  }
  ```
* Running tasks run inside the `worker` container, which shares the `./chroma_store/` volume to persist vector storage.

---

## 3. Conversational Session & Client Layer

* **Frontend Session Management**: [chat.html](file:///c:/Users/Tarek/Desktop/rag-chatbot/templates/chat.html)
  Generates a unique `localStorage` token to persist conversation sessions across browser tab refreshes:
  ```javascript
  let sessionId = localStorage.getItem("chat_session_id");
  if (!sessionId) {
    sessionId = "sess_" + Math.random().toString(36).substring(2, 11) + "_" + Date.now();
    localStorage.setItem("chat_session_id", sessionId);
  }
  ```
* **API Handlers**: [views.py](file:///c:/Users/Tarek/Desktop/rag-chatbot/api/views.py)
  - Django Rest Framework intercepts payload `POST /chat/`.
  - Extracts `message` and `session_id`, then initiates the state graph execution loop.

---

## 4. Conversational Retrieval & Inference Graph (Online Flow)

```
                       [POST /chat/ request]
                                 │
                                 v
                     [LangGraph Execution Loop]
                                 │
                                 v
                      [Intent Classifier Node]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼ (CHITCHAT)                    ▼ (KNOWLEDGE)
        [Direct LLM Answer]             [RAG Retrieval Node]
                 │                               │
                 │                      [1. Multi-Query Expansion]
                 │                               │
                 │                      [2. Parallel Vector Search]
                 │                               │
                 │                      [3. Merge & Deduplicate]
                 │                               │
                 │                      [4. Assemble Context & Answer]
                 │                               │
                 └───────────────┬───────────────┘
                                 v
                     [Update Memory & Summary]
                                 │
                                 v
                       [JSON Status 200 OK]
```

### 4.1 Intent Classification (`classify_intent`)
* **State Processing**:
  Reads the session ID to fetch the running summary and recent chat history from the in-memory store in [memory.py](file:///c:/Users/Tarek/Desktop/rag-chatbot/rag/memory.py).
* **Prompt Template**:
  ```text
  Classify the user's message as either CHITCHAT or KNOWLEDGE.
  Rules:
  - CHITCHAT: pure greetings, small talk, general conversation (e.g. 'hi', 'how are you', 'thank you') with no prior topic follow-up.
  - KNOWLEDGE: any question, statement, or follow-up question about a university, organization, person, place, acronym, fact, admission, program, fee, scholarship, or ranking.
  Note: If the prior conversation was about a university and the user asks a follow-up (e.g. 'what are the fees?', 'how to apply?'), always classify as KNOWLEDGE.
  
  Prior Conversation Summary / History:
  {conversation_summary}
  {chat_history}
  
  Message: {query}
  Respond with exactly one word: CHITCHAT or KNOWLEDGE.
  ```
* **Result**: Routes the message to either the `handle_chitchat` node or the `handle_knowledge` node.

### 4.2 Multi-Query Expansion & Retrieval Strategy
If routed to `KNOWLEDGE`, the system runs a multi-query retrieval sequence:
1. **Query Paraphrasing**:
   Using `llama-3.3-70b-versatile`, the system expands the query into 3 variations, resolving abbreviations and pronouns based on the conversation history:
   ```text
   Generate 3 different search queries/perspectives based on the user's latest query and the prior conversation context.
   The goal is to resolve pronouns/abbreviations and expand short or follow-up questions.
   Original Query: {query}
   ```
2. **Parallel Vector Retrieval**:
   Generates a 384-dimensional query vector for each query variation and searches ChromaDB:
   ```python
   query_vector = embeddings_model.embed_query(query_variation)
   results = similarity_search(query_vector, top_k=8)
   ```
3. **Merge and Deduplication**:
   Groups all retrieved chunks using `(source_ref, text)` as the unique key. If a chunk matches multiple queries, it keeps only the highest similarity score:
   $$\text{Merged Score} = \max(\{S_1, S_2, \dots, S_n\})$$
4. **Similarity Filtering**:
   Removes any chunk with a similarity score $< 0.3$.
5. **Context Block Compilation**:
   Sorts the remaining chunks by similarity score in descending order, selects the top `8` chunks, and formats them:
   ```text
   [{title}]
   Source: {source_ref}
   {text}
   ```

### 4.3 Answer Generation (`handle_knowledge`)
- Compiles the final prompt template containing the retrieved context, conversation summary, recent chat history, and the user's latest query.
- Prompts the LLM to write a concise, direct response for specific questions, or a structured response with headings for broad overview questions.
- **Model Fallback Configuration**:
  If the primary model (`llama-3.3-70b-versatile`) hits a rate limit or API error (HTTP 429), the execution loop catches the exception and retries the request using fallback models:
  ```python
  FALLBACK_MODELS = [
      "llama-3.3-70b-versatile",
      "llama-3.1-8b-instant",
      "mixtral-8x7b-32768",
      "openai/gpt-oss-20b"
  ]
  ```

### 4.4 Conversational Memory & Running Summary Update
- Saves the user turn and assistant reply to the session memory.
- Sends a background summarization request to compile a 2-3 sentence running summary, keeping input context payloads lightweight:
  ```text
  Create a concise 2-3 sentence running summary of the conversation so far, focusing on:
  - Universities or institutions mentioned
  - Specific programs, admission requirements, GPA criteria, fees, or topics asked about
  - Key answers provided
  ```
- Persists the updated summary to the session memory.

---

## 5. Output Delivery & Formatting

1. **REST API Delivery**:
   Returns the response payload:
   ```json
   {
       "answer": "BRAC University is located at **Kha 224 Pragati Sarani, Merul Badda, Dhaka 1212, Bangladesh**.",
       "intent": "KNOWLEDGE",
       "session_id": "sess_a8b9c10_12345678"
   }
   ```
2. **DOM Update**:
   - The frontend JavaScript uses `marked.js` to render Markdown tables, bullet lists, and headings.
   - Appends the card to the chat log container, scrolls to the bottom, and sets a source tag indicator (`"from the shelves"` or `"chitchat"`).

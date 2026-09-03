# UniRAG PRO — Architecture & System Design Specification

## 1. Executive Summary

**UniRAG PRO** is an enterprise-grade Retrieval-Augmented Generation (RAG) system specialized for Bangladeshi Higher Education institution data. It integrates hybrid lexical-dense vector search (Okapi BM25 + HuggingFace BGE Embeddings + ChromaDB), low-latency multi-model routing (Google Gemini 3.6 Flash + Groq OpenAI GPT-OSS-20B fallback), persistent session memory, multimodal document OCR processing, and Server-Sent Events (SSE) token streaming.

---

## 2. Architecture Diagram

```mermaid
flowchart TD
    User([User Browser / Client])
    
    subgraph UI ["Frontend (Glassmorphic Interface)"]
        ChatUI[Real-time SSE Stream Reader]
        VoiceInput[Web Speech API Speech Recognition]
        FileDrop[Multimodal File Attachment Dropzone]
    end

    subgraph API ["Django Web Server (Port 8000)"]
        StreamEndpoint["POST /chat/stream/ (SSE Endpoint)"]
        StandardEndpoint["POST /chat/ (JSON Endpoint)"]
        StatusEndpoint["GET /status/"]
        AdminEndpoint["/admin/documents/"]
    end

    subgraph RAG ["RAG Core Pipeline"]
        Router["Smart Intent Classifier & Fast-Path Router"]
        Retriever["Hybrid Vector & Lexical Retriever"]
        Memory["Persistent Session & Conversation Memory"]
        FileProc["Multimodal File & Vision Processor"]
    end

    subgraph VectorStore ["Local Storage & Indexing"]
        Chroma["ChromaDB Vector Database"]
        BM25["Okapi BM25 Sparse Index"]
        SQLite["Django DB & Memory SQLite Store"]
    end

    subgraph ExternalLLM ["LLM Providers & Fallback Chain"]
        Gemini["Google Gemini 3.6 Flash (Primary)"]
        Groq["Groq OpenAI GPT-OSS-20B (Ultra-Low Latency Fallback)"]
    end

    User -->|SSE Request| StreamEndpoint
    User -->|HTTP POST| StandardEndpoint
    StreamEndpoint --> Router
    StandardEndpoint --> Router

    Router -->|Check Intent| FastPath{Greeting / File?}
    FastPath -->|Greeting| Memory
    FastPath -->|Attached File| FileProc
    FastPath -->|Knowledge Query| Retriever

    FileProc --> Gemini
    FileProc --> Groq

    Retriever -->|Dense Embedding Search| Chroma
    Retriever -->|Sparse Lexical Search| BM25
    Retriever -->|Merge & Hybrid Rank| Router

    Router -->|Stream Prompt| Gemini
    Gemini -->|Quota Limit / Error 429| Groq
    
    Groq -->|SSE Stream Chunks| StreamEndpoint
    Gemini -->|SSE Stream Chunks| StreamEndpoint
    
    StreamEndpoint -->|Live Typing Stream| ChatUI
```

---

## 3. Core System Components

### 3.1. Hybrid Retrieval Engine (`rag/retriever.py` & `rag/bm25.py`)
- **Dense Vector Search**: Powered by `HuggingFaceBgeEmbeddings` (`BAAI/bge-small-en-v1.5`) running locally on CPU/GPU into ChromaDB SQLite store (`chroma_store/`).
- **Sparse Lexical Search**: Powered by custom Okapi BM25 implementation for exact keyword match (e.g., department codes, course names, acronyms like `BUET`, `DU`, `UIU`).
- **Multi-Query Optimization**: Standalone questions bypass LLM expansion for sub-100ms vector lookup, while contextual follow-ups automatically expand pronouns (`it`, `their`, `this`) into full search queries.

### 3.2. Low-Latency Multi-Model Router (`rag/router.py`)
- **Regex Fast-Path**: Greetings (`hi`, `hello`, `thanks`, `bye`) receive instant canned responses (< 5ms response time, 0 LLM calls).
- **Keyword Heuristic**: University questions skip intent classification LLM calls, reducing API latency from 3 calls down to 1 call per question.
- **Zero-Delay Fallback Strategy**:
  1. Primary Provider: **Google Gemini 3.6 Flash** (`gemini-3.6-flash`).
  2. Failover Provider: **Groq OpenAI GPT-OSS-20B** (`openai/gpt-oss-20b`).
  3. `max_retries=0` is configured on Gemini calls to eliminate 2-minute exponential backoff retry delays on free tier quota limit (`429 RESOURCE_EXHAUSTED`).

### 3.3. Real-Time SSE Token Streaming (`api/views.py`)
- Endpoint: `POST /chat/stream/`
- Emits `text/event-stream` chunks formatted as JSON:
  `data: {"content": "...", "intent": "KNOWLEDGE", "done": false}`
- Eliminates user loading delays; first token arrives in **~150ms**.

### 3.4. Session & Memory Persistence (`rag/memory.py`)
- File-backed persistent SQLite/JSON session store (`memory_store/`).
- Maintains rolling conversation summary and past chat turns for contextual multi-turn Q&A.

---

## 4. Ingestion & Data Pipeline

```
[University Source Files] -> [File Loader (PDF/Web)] -> [Recursive Character Text Splitter (Chunk Size: 600, Overlap: 100)] -> [Embeddings Engine] -> [ChromaDB & BM25 Persistence]
```

- **Indexed Data Volume**: 2,964 chunks across 205 University sources.
- **Multimodal OCR**: Images attached in chat are processed on-the-fly using `gemini-3.6-flash` vision / Groq vision.

---

## 5. API Reference

| Endpoint | Method | Content Type | Description |
| :--- | :--- | :--- | :--- |
| `/chat/stream/` | `POST` | `multipart/form-data` | **Real-time SSE token streaming** response for chat & attached files. |
| `/chat/` | `POST` | `application/json` / `multipart` | Standard JSON response containing full text answer and metadata. |
| `/status/` | `GET` | `application/json` | System health, indexed document count, and freshness timestamp. |
| `/admin/documents/`| `GET/POST/DELETE` | `application/json` | Document ingestion management API (protected by admin secret). |

---

## 6. Environment & Configuration

```env
# LLM Providers
GEMINI_API_KEY=AQ.Ab8RN...
GEMINI_MODEL=gemini-3.6-flash

GROQ_API_KEY=gsk_oPX...
GROQ_MODEL=openai/gpt-oss-20b

# Django Settings
DJANGO_SECRET_KEY=dev-only-change-me
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=*

# Storage Paths
PDF_SOURCE_DIR=./knowledge_base/pdfs
WEB_SOURCES_FILE=./knowledge_base/web_sources.txt
CHROMA_PERSIST_DIR=./chroma_store
```

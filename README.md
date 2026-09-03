# 🎓 UniRAG PRO — Enterprise Hybrid RAG System for Bangladeshi Universities

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django 6.0](https://img.shields.io/badge/Django-6.0-green.svg)](https://www.djangoproject.com/)
[![Gemini 3.6 Flash](https://img.shields.io/badge/LLM-Gemini_3.6_Flash-orange.svg)](https://ai.google.dev/)
[![Groq GPT-OSS-20B](https://img.shields.io/badge/Fallback-Groq_GPT--OSS--20B-purple.svg)](https://groq.com/)
[![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-red.svg)](https://www.trychroma.com/)
[![SSE Streaming](https://img.shields.io/badge/Streaming-Server--Sent_Events-cyan.svg)](#real-time-sse-token-streaming)

**UniRAG PRO** is a state-of-the-art Retrieval-Augmented Generation (RAG) platform specialized for Bangladeshi university admissions, GPA requirements, tuition fees, programs, and campus locations. It combines dense vector retrieval (`BAAI/bge-small-en-v1.5`), sparse lexical keyword matching (Okapi BM25), real-time Server-Sent Events (SSE) token streaming, low-latency LLM routing, and a ultra-modern glassmorphic UI.

---

## 🌟 Key Features

- **⚡ Real-Time SSE Token Streaming**: Experience live typewriter text rendering with sub-150ms time-to-first-token.
- **⚡ Dual LLM Provider Fallback**: Uses **Google Gemini 3.6 Flash** as primary engine with zero-delay fallback to **Groq (`openai/gpt-oss-20b`)** when API free quotas are exceeded.
- **🔍 Hybrid Vector & Lexical Retrieval**: Combines BM25 sparse keyword ranking with HuggingFace BGE dense vector search in ChromaDB SQLite store (2,964 indexed chunks across 205 university sources).
- **🎙️ Web Speech API Integration**: Built-in voice input for natural spoken questions.
- **📎 Multimodal File & Document Processing**: Drag-and-drop support for PDF documents, text files, and images with Gemini Vision OCR.
- **🎨 Glassmorphic Premium Interface**: Modern dark mode UI with interactive sample prompt cards, attachment chips, markdown formatting, syntax highlighting, and responsive mobile layout.

---

## 🏗️ Architecture & System Design

For a full technical breakdown of the multi-stage pipeline, router logic, and database schemas, see **[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md)**.

```mermaid
flowchart LR
    User[User Interface] -->|SSE Stream| Server[Django API /chat/stream/]
    Server --> Router[Intent Router]
    Router -->|Lexical + Vector Search| Chroma[ChromaDB + Okapi BM25]
    Chroma --> Context[Retrieved Context]
    Context --> Gemini[Google Gemini 3.6 Flash]
    Gemini -->|Quota Exceeded| Groq[Groq GPT-OSS-20B]
    Groq -->|Tokens| User
    Gemini -->|Tokens| User
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10+
- Git

### 2. Installation & Setup

```bash
# Clone the repository
git clone https://github.com/ArafathUIU/UniRAG_PRO.git
cd UniRAG_PRO

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the root directory:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
GEMINI_MODEL=gemini-3.6-flash

GROQ_API_KEY=YOUR_GROQ_API_KEY_HERE
GROQ_MODEL=openai/gpt-oss-20b

DJANGO_SECRET_KEY=dev-only-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=*
```

### 4. Database Migration & Knowledge Ingestion

```bash
# Apply migrations
python manage.py migrate

# Ingest university sources into vector store
python ingest.py
```

### 5. Run Development Server

```bash
python manage.py runserver 0.0.0.0:8000
```

Open your browser at **`http://localhost:8000/`**.

---

## 🧪 Testing

Run the automated unit test suite:

```bash
python manage.py test tests
```

---

## 📜 License & Credits

Built with ❤️ by **[ArafathUIU](https://github.com/ArafathUIU)** for Bangladeshi higher education search & knowledge discovery.

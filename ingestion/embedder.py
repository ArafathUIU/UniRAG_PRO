"""
Local embedding model — no external API calls, no rate limits, no API key.

Uses sentence-transformers running on your own machine/CPU. The first time
this runs it downloads the model (~90MB) from Hugging Face; after that it's
fully offline. This is what makes ingestion able to run start-to-finish
without stalling on Gemini's free-tier embedding rate limit.

NOTE ON DIMENSIONS: all-MiniLM-L6-v2 outputs 384-dim vectors. The
knowledge_chunks.embedding column in docker/init.sql is vector(384) to match.
If you swap to a different sentence-transformers model with a different
output size, update that column too and re-embed everything — dimensions
can't be mixed in one column (see the migration note in README.md if you're
upgrading an existing database that was on the old 768-dim Gemini vectors).

The chat LLM (rag/router.py, ChatGroq) is unaffected by this change and
still uses GROQ_API_KEY — only embeddings run locally.
"""
import os
import threading

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


class _LocalEmbeddings:
    """
    Mimics the embed_documents()/embed_query() interface that
    langchain_google_genai.GoogleGenerativeAIEmbeddings exposed, so
    rag/retriever.py doesn't need to change how it calls this.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = _get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


embeddings_model = _LocalEmbeddings()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embeds a batch of texts locally. No API calls, so no retry/backoff needed."""
    return embeddings_model.embed_documents(texts)

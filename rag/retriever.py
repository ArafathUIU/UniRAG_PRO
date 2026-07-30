import re
import logging
from django.conf import settings
from langchain_groq import ChatGroq
from ingestion.embedder import embeddings_model
from rag.vectorstore import similarity_search

logger = logging.getLogger(__name__)

def generate_query_variations(query: str, num_variations: int = 3, conversation_summary: str = "", chat_history: str = "") -> list[str]:
    queries = [query]
    api_key = getattr(settings, "GROQ_API_KEY", None)
    if not api_key:
        return queries
    return queries

def retrieve_context(query: str, top_k: int = 8, min_similarity: float = 0.3, conversation_summary: str = "", chat_history: str = "") -> str:
    queries = generate_query_variations(query, conversation_summary=conversation_summary, chat_history=chat_history)
    unique_results = {}
    for q in queries:
        query_vector = embeddings_model.embed_query(q)
        results = similarity_search(query_vector, top_k=top_k)
        for r in results:
            if r["similarity"] < min_similarity:
                continue
            key = (r["source_ref"] or "", r["text"] or "")
            if key not in unique_results or r["similarity"] > unique_results[key]["similarity"]:
                unique_results[key] = r
    if not unique_results:
        return ""
    sorted_results = sorted(unique_results.values(), key=lambda x: x["similarity"], reverse=True)[:top_k]
    return "\n\n---\n\n".join([f"[{r['title']}]\nSource: {r['source_ref']}\n{r['text']}" for r in sorted_results])

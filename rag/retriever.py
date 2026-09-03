import re
import logging
from django.conf import settings
from langchain_groq import ChatGroq
from ingestion.embedder import embeddings_model
from rag.vectorstore import similarity_search

logger = logging.getLogger(__name__)

_llm = None

def _get_llm():
    global _llm
    if _llm is None and getattr(settings, "GROQ_API_KEY", None):
        try:
            _llm = ChatGroq(
                model=settings.GROQ_MODEL,
                api_key=settings.GROQ_API_KEY,
                temperature=0.4,
            )
        except Exception as e:
            logger.warning(f"Could not initialize ChatGroq for query expansion: {e}")
    return _llm


def generate_query_variations(
    query: str,
    num_variations: int = 3,
    conversation_summary: str = "",
    chat_history: str = "",
) -> list[str]:
    """
    Generates alternative queries/perspectives based on the user's input query and past context.
    Falls back gracefully to returning just [query] if LLM is unavailable or fails.
    """
    queries = [query]
    # Optimization: Bypass extra LLM expansion call for standalone direct queries without prior conversation context
    if not conversation_summary and not chat_history:
        words = query.lower().split()
        if len(words) >= 3 and not any(p in words for p in ["it", "its", "they", "them", "their", "this", "that"]):
            return queries

    context_prompt = ""
    if conversation_summary:
        context_prompt += f"Conversation Summary So Far:\n{conversation_summary}\n\n"
    if chat_history:
        context_prompt += f"Recent Chat History:\n{chat_history}\n\n"

    prompt = (
        f"You are an AI assistant helping with information retrieval for Bangladeshi universities.\n"
        f"Generate {num_variations} different search queries/perspectives based on the user's latest query and the prior conversation context.\n"
        f"The goal is to resolve pronouns/abbreviations, expand acronyms (e.g. BUET -> Bangladesh University of Engineering and Technology), and expand short or follow-up questions.\n"
        f"Rules:\n"
        f"- Output exactly {num_variations} standalone search queries, one per line.\n"
        f"- Do NOT number the lines or add bullet points.\n"
        f"- Do NOT add explanations or preamble.\n\n"
        f"{context_prompt}"
        f"Latest User Query: {query}\n"
        f"Alternative Queries:"
    )

    try:
        from rag.router import invoke_llm_with_fallback
        raw_text = invoke_llm_with_fallback(prompt, temperature=0.4).strip()
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line in lines:
            # Strip leading numbers/bullets if any were produced
            cleaned = re.sub(r"^[\d\.\-\*\s]+", "", line).strip()
            if cleaned and cleaned.lower() != query.lower() and cleaned not in queries:
                queries.append(cleaned)
    except Exception as e:
        logger.warning(f"Multi-query expansion failed, using original query: {e}")

    return queries


def retrieve_context(
    query: str,
    top_k: int = 10,
    min_similarity: float = 0.25,
    conversation_summary: str = "",
    chat_history: str = "",
) -> str:
    """
    Multi-query retriever:
    1. Expands user query into multiple variations using conversation context.
    2. Performs similarity search for each query variation.
    3. Merges and deduplicates chunks, keeping the highest similarity score for duplicates.
    4. Ranks and returns top_k context blocks.
    """
    queries = generate_query_variations(
        query=query,
        conversation_summary=conversation_summary,
        chat_history=chat_history,
    )

    # Dictionary to deduplicate chunks: key = (source_ref, text)
    unique_results: dict[tuple[str, str], dict] = {}

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

    # Sort merged results by similarity score descending
    sorted_results = sorted(unique_results.values(), key=lambda x: x["similarity"], reverse=True)
    top_results = sorted_results[:top_k]

    context_blocks = [
        f"[{r['title']}]\nSource: {r['source_ref']}\n{r['text']}"
        for r in top_results
    ]
    return "\n\n---\n\n".join(context_blocks)




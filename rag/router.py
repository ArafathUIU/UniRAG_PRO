import re
import logging
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from django.conf import settings
from rag.retriever import retrieve_context
from rag.file_processor import is_fallback_only
from rag.memory import (
    get_conversation_summary,
    format_history_text,
    add_turn,
)

logger = logging.getLogger(__name__)

GEMINI_FALLBACK_MODELS = [
    getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash"),
    "gemini-3.6-flash",
    "gemini-2.5-flash",
]

GROQ_FALLBACK_MODELS = [
    getattr(settings, "GROQ_MODEL", "openai/gpt-oss-20b"),
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
]


def _extract_text_content(res_content) -> str:
    if isinstance(res_content, str):
        return res_content.strip()
    if isinstance(res_content, list):
        parts = []
        for item in res_content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(res_content).strip()


def invoke_llm_with_fallback(prompt: str, temperature: float = 0.3) -> str:
    """
    Invokes Google Gemini LLM (or Groq fallback) with fallback models if primary hits rate limits or errors.
    """
    gemini_key = getattr(settings, "GEMINI_API_KEY", None)
    groq_key = getattr(settings, "GROQ_API_KEY", None)

    if not gemini_key and not groq_key:
        raise ValueError("Neither GEMINI_API_KEY nor GROQ_API_KEY is configured.")

    last_error = None

    # Priority 1: Try Google Gemini models if key available
    if gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        tried = set()
        for model in GEMINI_FALLBACK_MODELS:
            if model in tried:
                continue
            tried.add(model)
            try:
                llm = ChatGoogleGenerativeAI(model=model, google_api_key=gemini_key, temperature=temperature, max_retries=0)
                res = llm.invoke(prompt)
                return _extract_text_content(res.content)
            except Exception as e:
                logger.warning(f"Gemini invocation failed for model '{model}': {e}. Trying next fallback...")
                last_error = e

    # Priority 2: Fall back to Groq models if key available
    if groq_key:
        tried = set()
        for model in GROQ_FALLBACK_MODELS:
            if model in tried:
                continue
            tried.add(model)
            try:
                llm = ChatGroq(model=model, api_key=groq_key, temperature=temperature)
                res = llm.invoke(prompt)
                return _extract_text_content(res.content)
            except Exception as e:
                logger.warning(f"Groq invocation failed for model '{model}': {e}. Trying next fallback...")
                last_error = e

    if last_error and "RESOURCE_EXHAUSTED" in str(last_error):
        return (
            "⚠️ **Google Gemini API daily free quota limit reached (20 requests/day).**\n\n"
            "Google resets free tier API quotas daily. To continue asking questions right now, "
            "you can add a free `GROQ_API_KEY` to your `.env` file or try again tomorrow."
        )

    raise RuntimeError(f"All LLM invocations failed. Last error: {last_error}")


class ChatState(TypedDict):
    session_id: str
    query: str
    intent: str
    context: str
    answer: str
    chat_history: str
    conversation_summary: str
    file_name: Optional[str]
    file_text: Optional[str]


# --- Instant greeting fast-path -------------------------------------------
# Simple greetings/thanks/farewells don't need the LLM at all. Detecting them
# here lets us reply instantly (0 LLM calls) instead of paying for two
# sequential Groq round-trips (classify + generate) on a plain "hi".
_GREETING_PATTERNS = re.compile(
    r"^(hi+|hey+|hello+|yo|heya|hiya|greetings|"
    r"good\s*(morning|afternoon|evening|day)|"
    r"a?ssalamu?\s*a?laikum|salam|nomoskar|namaste)"
    r"[\s!.,]*$",
    re.IGNORECASE,
)
_THANKS_PATTERNS = re.compile(
    r"^(thanks?|thank\s*you|thx|ty|tnx|shukriya|dhonnobad)[\s!.,you]*$",
    re.IGNORECASE,
)
_FAREWELL_PATTERNS = re.compile(
    r"^(bye+|goodbye|good\s*night|see\s*you|take\s*care)[\s!.,]*$",
    re.IGNORECASE,
)

_GREETING_REPLY = (
    "Hello! 👋 I'm **UniRAG**, your assistant for Bangladeshi university "
    "admissions, programs, GPA requirements, fees, and scholarships. "
    "What would you like to know?"
)
_THANKS_REPLY = "You're welcome! 😊 Feel free to ask me anything else about universities in Bangladesh."
_FAREWELL_REPLY = "Goodbye! 👋 Come back anytime you have questions about university admissions."


def _fast_reply(query: str) -> Optional[str]:
    """Returns an instant canned reply for trivial greetings, else None."""
    q = (query or "").strip()
    if not q or len(q) > 40:
        return None
    if _GREETING_PATTERNS.match(q):
        return _GREETING_REPLY
    if _THANKS_PATTERNS.match(q):
        return _THANKS_REPLY
    if _FAREWELL_PATTERNS.match(q):
        return _FAREWELL_REPLY
    return None


_KNOWLEDGE_KEYWORDS = re.compile(
    r"\b(university|admission|fee|fees|gpa|requirement|requirements|program|programs|scholarship|"
    r"cost|tuition|location|address|where|what|how|can\s+you|tell\s+me|about|buet|du|nsu|uiu|bracu|"
    r"brac|bup|sust|ju|diu|aiub|buft|iiustb|ece|cse|eee|mba|bba|msc|bsc|dept|department)\b|\?",
    re.IGNORECASE,
)


def classify_intent(state: ChatState) -> ChatState:
    session_id = state.get("session_id", "default")

    # If a file is attached, force KNOWLEDGE intent to process attached file
    if state.get("file_text") and state["file_text"].strip():
        state["conversation_summary"] = get_conversation_summary(session_id)
        state["chat_history"] = format_history_text(session_id)
        state["intent"] = "KNOWLEDGE"
        return state

    # Fast-path 1: instant canned reply for greetings/thanks/farewells (0 LLM calls).
    fast = _fast_reply(state["query"])
    if fast is not None:
        state["intent"] = "GREETING"
        state["answer"] = fast
        add_turn(session_id, state["query"], fast)
        return state

    summary = get_conversation_summary(session_id)
    history = format_history_text(session_id)
    state["conversation_summary"] = summary
    state["chat_history"] = history

    # Fast-path 2: Heuristic keyword/question matching (0 LLM classification calls).
    if _KNOWLEDGE_KEYWORDS.search(state["query"]) or len(state["query"].split()) >= 3:
        state["intent"] = "KNOWLEDGE"
        return state

    context_hint = ""
    if summary or history:
        context_hint = f"Prior Conversation Summary / History:\n{summary}\n{history}\n\n"

    prompt = (
        "Classify the user's message as either CHITCHAT or KNOWLEDGE.\n"
        "Rules:\n"
        "- CHITCHAT: pure greetings, small talk, general conversation (e.g. 'hi', 'how are you', 'thank you') with no prior topic follow-up.\n"
        "- KNOWLEDGE: any question, statement, or follow-up question about a university, organization, person, place, "
        "acronym, fact, admission, program, fee, scholarship, ranking, or attached file content.\n\n"
        f"{context_hint}"
        f"Message: {state['query']}\n"
        "Respond with exactly one word: CHITCHAT or KNOWLEDGE."
    )
    try:
        result = invoke_llm_with_fallback(prompt, temperature=0.2).strip().upper()
        state["intent"] = "KNOWLEDGE" if "KNOWLEDGE" in result else "CHITCHAT"
    except Exception as e:
        logger.warning(f"Intent classification LLM call failed ({e}), defaulting to KNOWLEDGE.")
        state["intent"] = "KNOWLEDGE"
    return state


def handle_chitchat(state: ChatState) -> ChatState:
    session_id = state.get("session_id", "default")
    summary = state.get("conversation_summary", "")

    prompt = state["query"]
    if summary:
        prompt = f"Context of previous chat:\n{summary}\n\nUser message: {state['query']}"

    state["answer"] = invoke_llm_with_fallback(prompt, temperature=0.7)

    # Save turn to memory
    add_turn(session_id, state["query"], state["answer"])
    return state


def handle_knowledge(state: ChatState) -> ChatState:
    session_id = state.get("session_id", "default")
    summary = state.get("conversation_summary", "")
    history = state.get("chat_history", "")
    file_name = state.get("file_name", "attached file")
    file_text = state.get("file_text")

    # If a file is attached, run hierarchical resolution
    if file_text and file_text.strip():
        logger.info(f"Processing attached file '{file_name}' ({len(file_text)} chars) for query: {state['query']}")

        is_fallback_text = is_fallback_only(file_text)

        query_lower = state["query"].lower()
        is_describe_query = any(kw in query_lower for kw in [
            "describe", "what is this", "what's in", "explain", "summarize", "detail", "tell me about this", "show", "image", "picture", "photo"
        ]) or not state["query"].strip()

        if not is_fallback_text:
            # Step 0: Check Domain Relevance of attached document/picture
            relevance_prompt = (
                "You are evaluating if an attached file/image or user query is relevant to the UniRAG domain.\n"
                "UniRAG Domain: Higher education, universities, admissions, academic programs, degrees, tuition fees, "
                "course curriculum, academic requirements, student administration, campus info, exams, certificates, or academic documents.\n\n"
                f"File Name: {file_name}\n"
                f"Extracted File Content / Image Description:\n{file_text[:2500]}\n\n"
                f"User Query: {state['query']}\n\n"
                "Rules:\n"
                "- If the user asks to describe, explain, identify, or answer questions from the attached document/picture, OR if the document relates to education/academics/universities/documents, answer RELEVANT.\n"
                "- If the document is completely unrelated (e.g. food recipes, sports news, movie scripts, car repair manuals), answer IRRELEVANT.\n\n"
                "Respond with exactly one word: RELEVANT or IRRELEVANT."
            )
            try:
                rel_result = invoke_llm_with_fallback(relevance_prompt, temperature=0.1).strip().upper()
            except Exception as e:
                logger.warning(f"Relevance check failed ({e}), defaulting to RELEVANT.")
                rel_result = "RELEVANT"

            if "IRRELEVANT" in rel_result and not is_describe_query:
                state["answer"] = "Sorry, this is not covered in this chatbot."
                state["intent"] = "ATTACHED_FILE"
                add_turn(session_id, state["query"], state["answer"])
                return state

            # Step 1: Check if Attached File/Image contains the answer or if user asks for description
            check_file_prompt = (
                "Determine if the attached file/image content or description contains relevant information to answer the user's query.\n\n"
                f"File Name: {file_name}\n"
                f"Attached Content / Description:\n{file_text[:10000]}\n\n"
                f"User Question: {state['query']}\n\n"
                "Rules:\n"
                "- If the user asks to describe, explain, summarize, or identify the attached file/image, OR if the attached content contains information to answer the user's question, respond with YES.\n"
                "- Otherwise, respond with NO.\n\n"
                "Respond with EXACTLY one word: YES or NO."
            )
            try:
                has_info = invoke_llm_with_fallback(check_file_prompt, temperature=0.1).strip().upper()
            except Exception as e:
                logger.warning(f"Check file prompt error ({e}), proceeding to answer attempt.")
                has_info = "YES"

            if "YES" in has_info or is_describe_query:
                answer_prompt = (
                    "You are an expert AI assistant analyzing an attached document or image.\n\n"
                    f"File Name: {file_name}\n"
                    f"Attached File Content / Image Description:\n{file_text[:12000]}\n\n"
                    f"User Question: {state['query']}\n\n"
                    "INSTRUCTIONS:\n"
                    "1. Provide a thorough, accurate, and detailed answer using the attached file content / image description.\n"
                    "2. If the user asks to describe, explain, or summarize the image or document, provide a rich, structured description highlighting visual details and any text.\n"
                    "3. Use bold formatting for key facts, names, dates, numbers, and important details."
                )
                state["answer"] = invoke_llm_with_fallback(answer_prompt, temperature=0.2).strip()
                state["intent"] = "ATTACHED_FILE"
                add_turn(session_id, state["query"], state["answer"])
                return state

        # If vision extraction returned fallback text, augment search with filename keywords!
        if is_fallback_text:
            clean_file_topic = file_name.replace("_", " ").replace("-", " ").split(".")[0]
            augmented_query = f"{state['query']} {clean_file_topic}".strip()
            context = retrieve_context(
                query=augmented_query,
                conversation_summary=summary,
                chat_history=history,
            )
            if context:
                prompt = (
                    "You are a helpful university knowledge assistant for Bangladeshi universities.\n"
                    f"The user attached an image/file named '{file_name}' and asked: '{state['query']}'.\n\n"
                    "Using the retrieved knowledge base context below, provide a complete, clear, and informative answer about the topic.\n\n"
                    f"Context:\n{context}\n\n"
                    "Answer:"
                )
                state["answer"] = invoke_llm_with_fallback(prompt, temperature=0.3)
                state["intent"] = "KNOWLEDGE"
                add_turn(session_id, state["query"], state["answer"])
                return state

    # Step 2: Search in Knowledge Base (Vectorstore)
    context = retrieve_context(
        query=state["query"],
        conversation_summary=summary,
        chat_history=history,
    )
    state["context"] = context

    # Step 3: Fallback if not found in Knowledge Base either
    if not context:
        state["answer"] = "No information was found."
        add_turn(session_id, state["query"], state["answer"])
        return state

    history_prompt = ""
    if summary:
        history_prompt += f"Prior Conversation Summary:\n{summary}\n\n"
    if history:
        history_prompt += f"Recent Chat History:\n{history}\n\n"

    prompt = (
        "You are a helpful university knowledge assistant for Bangladeshi universities.\n"
        "Using the retrieved context below and prior conversation summary, answer the user's question accurately.\n\n"
        "CRITICAL RULES:\n"
        "1. MATCH ANSWER SCOPE TO QUERY TYPE:\n"
        "   - FOR SPECIFIC / DIRECT QUESTIONS (e.g. 'where is BRAC University located?', 'what is the contact number?', 'what is the minimum GPA?'):\n"
        "     Give a direct, concise, to-the-point answer answering EXACTLY what was asked. Do NOT generate unnecessary extra sections.\n"
        "   - FOR BROAD / OVERVIEW QUESTIONS (e.g. 'Tell me about BUET', 'Overview of NSU', 'Details on DIU admission'):\n"
        "     Structure comprehensively with clear headings (Overview, Campus & Enrollment, Academics, Admission, Fees).\n"
        "2. ALWAYS use the retrieved context to answer — never say 'I don't have information' if the context is relevant.\n"
        "3. Support common university abbreviations (e.g. DIU, NSU, BUET, BRACU, UIU, SUST, BUP, etc.).\n"
        "4. Bold key facts, locations, requirements, dates, and figures.\n"
        "5. ONLY say you don't have information if the context contains nothing relevant.\n\n"
        f"{history_prompt}"
        f"Context:\n{context}\n\n"
        f"User Question: {state['query']}\n\n"
        "Answer:"
    )
    state["answer"] = invoke_llm_with_fallback(prompt, temperature=0.3)

    # Save turn to memory
    add_turn(session_id, state["query"], state["answer"])
    return state


def route(state: ChatState) -> str:
    if state["intent"] == "GREETING":
        # Answer already set by the fast-path — skip all LLM nodes.
        return "greeting"
    return "knowledge" if state["intent"] == "KNOWLEDGE" else "chitchat"


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("classify", classify_intent)
    graph.add_node("chitchat", handle_chitchat)
    graph.add_node("knowledge", handle_knowledge)

    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route, {
        "greeting": END,
        "chitchat": "chitchat",
        "knowledge": "knowledge",
    })
    graph.add_edge("chitchat", END)
    graph.add_edge("knowledge", END)

    return graph.compile()


chat_graph = build_graph()

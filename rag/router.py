import logging
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from django.conf import settings
from rag.retriever import retrieve_context
from rag.memory import get_conversation_summary, format_history_text, add_turn

logger = logging.getLogger(__name__)

def invoke_llm_with_fallback(prompt: str, temperature: float = 0.3) -> str:
    api_key = getattr(settings, "GROQ_API_KEY", None)
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured.")
    llm = ChatGroq(model=getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"), api_key=api_key, temperature=temperature)
    return llm.invoke(prompt).content

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

def classify_intent(state: ChatState) -> ChatState:
    state["intent"] = "KNOWLEDGE"
    return state

def handle_knowledge(state: ChatState) -> ChatState:
    context = retrieve_context(state["query"])
    state["context"] = context
    state["answer"] = f"Retrieved information: {context[:200]}"
    return state

def route(state: ChatState) -> str:
    return "knowledge"

def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("classify", classify_intent)
    graph.add_node("knowledge", handle_knowledge)
    graph.set_entry_point("classify")
    graph.add_edge("classify", "knowledge")
    graph.add_edge("knowledge", END)
    return graph.compile()

chat_graph = build_graph()

import logging
logger = logging.getLogger(__name__)

_sessions = {}
_summaries = {}

def get_history(session_id: str):
    return list(_sessions.get(session_id, []))

def format_history_text(session_id: str, max_turns: int = 4) -> str:
    turns = _sessions.get(session_id, [])
    if not turns:
        return ""
    recent = turns[-max_turns:]
    parts = []
    for t in recent:
        parts.append(f"User: {t['query']}")
        parts.append(f"Assistant: {t['answer']}")
    return "\n".join(parts)

def get_conversation_summary(session_id: str) -> str:
    return _summaries.get(session_id, "")

def add_turn(session_id: str, query: str, answer: str):
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({"query": query, "answer": answer})

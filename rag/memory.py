import os
import json
import logging
from typing import Optional
from django.conf import settings

logger = logging.getLogger(__name__)

_MEMORY_DIR = os.path.join(getattr(settings, "BASE_DIR", "."), "memory_store")
_SESSIONS_FILE = os.path.join(_MEMORY_DIR, "sessions.json")
_SUMMARIES_FILE = os.path.join(_MEMORY_DIR, "summaries.json")
os.makedirs(_MEMORY_DIR, exist_ok=True)

def _load_json(filepath: str) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load memory file '{filepath}': {e}")
    return {}

def _save_json(filepath: str, data: dict):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save memory file '{filepath}': {e}")

_sessions: dict[str, list[dict[str, str]]] = _load_json(_SESSIONS_FILE)
_summaries: dict[str, str] = _load_json(_SUMMARIES_FILE)

def get_history(session_id: str) -> list[dict[str, str]]:
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
    _save_json(_SESSIONS_FILE, _sessions)

def clear_session(session_id: str):
    _sessions.pop(session_id, None)
    _summaries.pop(session_id, None)
    _save_json(_SESSIONS_FILE, _sessions)
    _save_json(_SUMMARIES_FILE, _summaries)

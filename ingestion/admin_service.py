"""
Admin-facing knowledge base management: list, add (file or pasted text), and
delete documents. Adding a document immediately chunks, embeds, and upserts it
into ChromaDB; deleting removes its vectors (and the on-disk file) so the
knowledge base no longer contains it.

Files live under settings.ADMIN_UPLOAD_DIR so the scheduled pipeline re-ingests
them on its periodic rebuild — see ingestion/loaders/admin_loader.py.
"""
import os
import re
import time

from django.conf import settings

from ingestion.chunker import chunk_document
from ingestion.embedder import embed_texts
from ingestion.loaders.admin_loader import load_one_file
from rag.vectorstore import (
    list_sources,
    upsert_chunks,
    delete_chunks_for_source,
)


def _upload_dir() -> str:
    d = settings.ADMIN_UPLOAD_DIR
    os.makedirs(d, exist_ok=True)
    return d


def _safe_filename(name: str) -> str:
    """Strips any path components and unsafe characters from an upload name."""
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    return name or f"document_{int(time.time())}"


def _unique_path(directory: str, filename: str) -> str:
    """Returns a non-colliding path in directory for filename."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{i}{ext}")
        i += 1
    return candidate


def _within_knowledge_base(path: str) -> bool:
    """True only if path resolves inside the knowledge_base tree (delete guard)."""
    kb = os.path.abspath(os.path.join(settings.BASE_DIR, "knowledge_base"))
    try:
        ap = os.path.abspath(path)
        return os.path.commonpath([kb, ap]) == kb
    except (ValueError, TypeError):
        return False


def _ingest_saved_path(path: str) -> dict:
    """Chunks, embeds, and upserts a saved file. Returns a summary dict."""
    doc = load_one_file(path)
    if not doc:
        # Nothing usable extracted — don't leave an orphan file behind.
        if os.path.isfile(path):
            os.remove(path)
        raise ValueError("No extractable text could be read from the document.")

    # Replace any existing vectors for this source before inserting fresh ones.
    delete_chunks_for_source(doc["source_ref"])
    chunks = chunk_document(doc)
    if not chunks:
        if os.path.isfile(path):
            os.remove(path)
        raise ValueError("Document produced no chunks.")

    vectors = embed_texts([c["text"] for c in chunks])
    upsert_chunks(chunks, vectors)

    return {
        "source_ref": doc["source_ref"],
        "title": doc["title"],
        "source_type": doc["source_type"],
        "chunk_count": len(chunks),
    }


def list_documents() -> list[dict]:
    """Lists all indexed knowledge base sources for the admin view."""
    return list_sources()


def add_document_from_file(file_obj, file_name: str) -> dict:
    """Saves an uploaded file to the KB and ingests it into ChromaDB."""
    directory = _upload_dir()
    path = _unique_path(directory, _safe_filename(file_name))
    with open(path, "wb") as out:
        if hasattr(file_obj, "chunks"):
            for chunk in file_obj.chunks():
                out.write(chunk)
        else:
            out.write(file_obj.read())
    return _ingest_saved_path(path)


def add_document_from_text(title: str, text: str) -> dict:
    """Saves pasted text as a .txt document in the KB and ingests it."""
    if not text or not text.strip():
        raise ValueError("Text content is required.")
    directory = _upload_dir()
    base = _safe_filename(title or "note")
    if not base.lower().endswith(".txt"):
        base += ".txt"
    path = _unique_path(directory, base)
    with open(path, "w", encoding="utf-8") as out:
        out.write(text)
    return _ingest_saved_path(path)


def delete_document(source_ref: str) -> dict:
    """
    Removes a document's vectors from ChromaDB, and deletes its on-disk file
    when it lives inside the knowledge_base tree (so the scheduled pipeline
    won't re-ingest it). Web sources have no local file — only vectors go.
    """
    if not source_ref:
        raise ValueError("source_ref is required.")

    delete_chunks_for_source(source_ref)

    removed_file = False
    if _within_knowledge_base(source_ref) and os.path.isfile(source_ref):
        os.remove(source_ref)
        removed_file = True

    return {"source_ref": source_ref, "removed_file": removed_file}

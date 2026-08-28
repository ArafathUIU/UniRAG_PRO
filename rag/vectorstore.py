"""
ChromaDB-backed knowledge store (persistent, SQLite-based, fully local —
no separate database server to run or manage).

chromadb.PersistentClient stores everything under CHROMA_PERSIST_DIR
(config/settings.py) as a SQLite file plus its HNSW index files. This
replaced the earlier Postgres + pgvector setup — nothing else in this
project needed pgvector specifically, so this drops an entire container
from docker-compose.yml.

All functions here keep the exact same names/signatures the rest of the
app already calls (ingestion/pipeline.py, rag/retriever.py, api/views.py),
so nothing outside this file needed to change.
"""
import hashlib
import threading
import time
from datetime import datetime, timezone

import chromadb
from django.conf import settings

COLLECTION_NAME = "knowledge_chunks"

_client = None
_collection = None
_lock = threading.Lock()


def _get_collection():
    global _client, _collection
    if _collection is None:
        with _lock:
            if _collection is None:
                _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
                _collection = _client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
    return _collection


def _chunk_id(source_ref: str, chunk_index: int) -> str:
    """
    Stable ID per (source, chunk position) so re-upserting the same chunk
    overwrites it instead of duplicating. Hashed to keep IDs short and safe
    even when source_ref is a long URL.
    """
    ref_hash = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    return f"{ref_hash}-{chunk_index}"


def clear_all_chunks():
    """Wipes the entire vector database collection to clear old knowledge base data."""
    collection = _get_collection()
    data = collection.get(include=[])
    if data and data.get("ids"):
        collection.delete(ids=data["ids"])


def delete_chunks_for_source(source_ref: str):
    """Removes old chunks for a source before inserting refreshed content."""
    _get_collection().delete(where={"source_ref": source_ref})


def source_unchanged(source_ref: str, content_hash: str) -> bool:
    """Checks if this source's content hash already matches what's stored."""
    result = _get_collection().get(
        where={"source_ref": source_ref},
        limit=1,
        include=["metadatas"],
    )
    metadatas = result.get("metadatas") or []
    if not metadatas:
        return False
    return metadatas[0].get("content_hash") == content_hash


def upsert_chunks(chunks: list[dict], vectors: list[list[float]], batch_size: int = 50):
    if not chunks:
        return

    now = time.time()
    ids, metadatas, documents = [], [], []
    for chunk in chunks:
        ids.append(_chunk_id(chunk["source_ref"], chunk["chunk_index"]))
        metadatas.append({
            "source_type": chunk["source_type"],
            "source_ref": chunk["source_ref"],
            "title": chunk["title"] or "",
            "content_hash": chunk["content_hash"],
            "chunk_index": chunk["chunk_index"],
            "updated_at": now,
        })
        documents.append(chunk["text"])

    # Upsert in small batches to avoid ChromaDB compaction errors on large documents
    collection = _get_collection()
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            embeddings=vectors[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
            documents=documents[i:i + batch_size],
        )


def get_last_updated():
    """Returns the most recent updated_at timestamp across all chunks, or None if empty."""
    result = _get_collection().get(include=["metadatas"])
    metadatas = result.get("metadatas") or []
    if not metadatas:
        return None
    latest = max(m.get("updated_at", 0) for m in metadatas)
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def get_source_count():
    """Returns the number of distinct sources currently indexed."""
    result = _get_collection().get(include=["metadatas"])
    metadatas = result.get("metadatas") or []
    return len({m.get("source_ref") for m in metadatas})


def list_sources() -> list[dict]:
    """
    Returns one entry per distinct indexed source, for the admin document view:
    {source_ref, source_type, title, chunk_count, updated_at}. Sorted newest
    first by updated_at.
    """
    result = _get_collection().get(include=["metadatas"])
    metadatas = result.get("metadatas") or []

    sources: dict[str, dict] = {}
    for m in metadatas:
        ref = m.get("source_ref") or ""
        entry = sources.get(ref)
        if entry is None:
            sources[ref] = {
                "source_ref": ref,
                "source_type": m.get("source_type") or "",
                "title": m.get("title") or "",
                "chunk_count": 1,
                "updated_at": m.get("updated_at", 0),
            }
        else:
            entry["chunk_count"] += 1
            entry["updated_at"] = max(entry["updated_at"], m.get("updated_at", 0))

    out = list(sources.values())
    out.sort(key=lambda e: e["updated_at"], reverse=True)
    for e in out:
        ts = e["updated_at"]
        e["updated_at"] = (
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None
        )
    return out


def similarity_search(query_vector: list[float], top_k: int = 5) -> list[dict]:
    collection = _get_collection()
    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, collection.count()),
        include=["metadatas", "documents", "distances"],
    )

    metadatas = results.get("metadatas", [[]])[0]
    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    out = []
    for meta, text, distance in zip(metadatas, documents, distances):
        # collection uses cosine space, and embeddings are normalized at
        # embedding time, so cosine distance == 1 - cosine similarity
        similarity = 1 - distance
        out.append({
            "title": meta.get("title"),
            "text": text,
            "source_ref": meta.get("source_ref"),
            "similarity": similarity,
        })
    return out

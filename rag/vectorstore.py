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
    ref_hash = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    return f"{ref_hash}-{chunk_index}"

def clear_all_chunks():
    collection = _get_collection()
    data = collection.get(include=[])
    if data and data.get("ids"):
        collection.delete(ids=data["ids"])

def delete_chunks_for_source(source_ref: str):
    _get_collection().delete(where={"source_ref": source_ref})

def source_unchanged(source_ref: str, content_hash: str) -> bool:
    result = _get_collection().get(
        where={"source_ref": source_ref},
        limit=1,
        include=["metadatas"],
    )
    metadatas = result.get("metadatas") or []
    if not metadatas:
        return False
    return metadatas[0].get("content_hash") == content_hash

def upsert_chunks(chunks: list[dict], vectors: list[list[float]]):
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
    _get_collection().upsert(ids=ids, embeddings=vectors, metadatas=metadatas, documents=documents)

def get_last_updated():
    result = _get_collection().get(include=["metadatas"])
    metadatas = result.get("metadatas") or []
    if not metadatas:
        return None
    latest = max(m.get("updated_at", 0) for m in metadatas)
    return datetime.fromtimestamp(latest, tz=timezone.utc)

def get_source_count():
    result = _get_collection().get(include=["metadatas"])
    metadatas = result.get("metadatas") or []
    return len({m.get("source_ref") for m in metadatas})

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
        out.append({
            "title": meta.get("title"),
            "text": text,
            "source_ref": meta.get("source_ref"),
            "similarity": 1 - distance,
        })
    return out

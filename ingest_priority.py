"""
Targeted ingestion for Daffodil International University and North South University pages.
Run this AFTER the main ingestion completes to ensure these key universities are indexed.
"""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from ingestion.loaders.web_loader import _clean_text, _extract_relevant_sublinks, HEADERS
from ingestion.chunker import chunk_document
from ingestion.embedder import embed_texts
from rag.vectorstore import delete_chunks_for_source, upsert_chunks, source_unchanged, _get_collection
import hashlib
import requests

PRIORITY_URLS = [
    # Daffodil International University — explicit sub-pages
    "https://www.daffodilvarsity.edu.bd",
    "https://www.daffodilvarsity.edu.bd/about",
    "https://www.daffodilvarsity.edu.bd/admission",
    "https://www.daffodilvarsity.edu.bd/tuition-fee",
    "https://www.daffodilvarsity.edu.bd/scholarship",
    "https://www.daffodilvarsity.edu.bd/program",
    "https://www.daffodilvarsity.edu.bd/academic",
    "https://www.daffodilvarsity.edu.bd/research",
    "https://www.daffodilvarsity.edu.bd/campus-life",
    # North South University — explicit sub-pages
    "https://www.northsouth.edu",
    "https://www.northsouth.edu/admission/",
    "https://www.northsouth.edu/academics/",
    "https://www.northsouth.edu/fees-financial-aid/",
    "https://www.northsouth.edu/scholarships/",
    "https://www.northsouth.edu/about-nsu/",
]

print(f"[targeted] Starting ingestion for {len(PRIORITY_URLS)} priority pages...")
total_chunks = 0
indexed = 0

for url in PRIORITY_URLS:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        resp.raise_for_status()
    except Exception as e:
        print(f"[targeted] FAILED: {url} — {e}")
        continue

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else url
    raw_text = _clean_text(resp.text)

    if len(raw_text) < 100:
        print(f"[targeted] EMPTY: {url}")
        continue

    content_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    doc = {
        "source_type": "web",
        "source_ref": url,
        "title": title,
        "raw_text": raw_text,
        "content_hash": content_hash,
    }

    delete_chunks_for_source(url)
    chunks = chunk_document(doc)
    if chunks:
        vectors = embed_texts([c["text"] for c in chunks])
        upsert_chunks(chunks, vectors)
        total_chunks += len(chunks)
        indexed += 1
        print(f"[targeted] OK: {len(chunks)} chunks — {title[:60]} | {url}")
    else:
        print(f"[targeted] NO CHUNKS: {url}")

print(f"\n[targeted] Done. {indexed} pages indexed, {total_chunks} total chunks added.")
col = _get_collection()
print(f"[targeted] ChromaDB now has {col.count()} total chunks across all sources.")

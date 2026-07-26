"""
Index only the remaining PDFs that weren't processed before the crash.
Run after the main ingestion to complete the PDF indexing.
"""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from ingestion.loaders.pdf_loader import load_pdf_sources
from ingestion.chunker import chunk_document
from ingestion.embedder import embed_texts
from rag.vectorstore import delete_chunks_for_source, upsert_chunks, source_unchanged, _get_collection

# Only process the PDFs that were NOT indexed yet (crashed after BUP.pdf)
REMAINING_PDFS = [
    "./knowledge_base/pdfs/DIU.pdf",
    "./knowledge_base/pdfs/DU.pdf",
    "./knowledge_base/pdfs/JU.pdf",
    "./knowledge_base/pdfs/NSU.pdf",
    "./knowledge_base/pdfs/SUST.pdf",
    "./knowledge_base/pdfs/UIU.pdf",
]

print(f"[pdf-ingest] Indexing {len(REMAINING_PDFS)} remaining PDFs into ChromaDB...")
all_docs = load_pdf_sources(settings.PDF_SOURCE_DIR)
# Filter only the remaining ones
docs_to_index = [d for d in all_docs if any(r in d["source_ref"] for r in REMAINING_PDFS)]
print(f"[pdf-ingest] Found {len(docs_to_index)} matching PDF documents.")

total_chunks = 0
for i, doc in enumerate(docs_to_index, 1):
    delete_chunks_for_source(doc["source_ref"])
    chunks = chunk_document(doc)
    if chunks:
        vectors = embed_texts([c["text"] for c in chunks])
        upsert_chunks(chunks, vectors)
        total_chunks += len(chunks)
        print(f"[pdf-ingest] ({i}/{len(docs_to_index)}) {len(chunks)} chunks indexed for: {doc['source_ref']}")

col = _get_collection()
print(f"\n[pdf-ingest] Done! {total_chunks} chunks added from PDFs.")
print(f"[pdf-ingest] ChromaDB now holds {col.count()} total chunks across {len(set())} sources.")

from django.conf import settings
from ingestion.loaders.web_loader import load_web_sources, read_source_list
from ingestion.loaders.pdf_loader import load_pdf_sources
from ingestion.loaders.admin_loader import load_admin_uploads
from ingestion.chunker import chunk_document
from ingestion.embedder import embed_texts
from rag.vectorstore import source_unchanged, delete_chunks_for_source, upsert_chunks, clear_all_chunks


def run_ingestion(reset_kb: bool = True):
    web_urls = read_source_list(settings.WEB_SOURCES_FILE)
    print(f"[pipeline] loaded {len(web_urls)} root web URLs from source list.")

    if reset_kb:
        print("[pipeline] clearing previous knowledge base from ChromaDB as requested...")
        clear_all_chunks()

    total_chunks = 0
    doc_count = 0

    print("[pipeline] starting web scraping & sub-page crawling across all sectors...")
    for doc in load_web_sources(web_urls):
        doc_count += 1
        if not reset_kb and source_unchanged(doc["source_ref"], doc["content_hash"]):
            print(f"[pipeline] ({doc_count}) unchanged, skipping: {doc['source_ref']}")
            continue

        delete_chunks_for_source(doc["source_ref"])
        chunks = chunk_document(doc)
        if chunks:
            vectors = embed_texts([c["text"] for c in chunks])
            upsert_chunks(chunks, vectors)
            total_chunks += len(chunks)
            print(f"[pipeline] ({doc_count}) indexed {len(chunks)} chunks into DB for: {doc['source_ref']}")

    print("[pipeline] loading PDF sources...")
    pdf_docs = load_pdf_sources(settings.PDF_SOURCE_DIR)
    for doc in pdf_docs:
        doc_count += 1
        if not reset_kb and source_unchanged(doc["source_ref"], doc["content_hash"]):
            continue

        delete_chunks_for_source(doc["source_ref"])
        chunks = chunk_document(doc)
        if chunks:
            vectors = embed_texts([c["text"] for c in chunks])
            upsert_chunks(chunks, vectors)
            total_chunks += len(chunks)
            print(f"[pipeline] ({doc_count}) indexed {len(chunks)} chunks into DB for PDF: {doc['source_ref']}")

    print("[pipeline] loading admin-uploaded documents...")
    admin_dir = getattr(settings, "ADMIN_UPLOAD_DIR", None)
    admin_docs = load_admin_uploads(admin_dir) if admin_dir else []
    for doc in admin_docs:
        doc_count += 1
        if not reset_kb and source_unchanged(doc["source_ref"], doc["content_hash"]):
            continue

        delete_chunks_for_source(doc["source_ref"])
        chunks = chunk_document(doc)
        if chunks:
            vectors = embed_texts([c["text"] for c in chunks])
            upsert_chunks(chunks, vectors)
            total_chunks += len(chunks)
            print(f"[pipeline] ({doc_count}) indexed {len(chunks)} chunks into DB for admin doc: {doc['source_ref']}")

    print(f"[pipeline] Ingestion complete! Total chunks indexed in ChromaDB: {total_chunks}")



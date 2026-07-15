"""Reads PDFs from a source directory and returns normalized documents."""
import hashlib
import os
import fitz  # PyMuPDF


def load_pdf_sources(directory: str) -> list[dict]:
    documents = []
    if not os.path.isdir(directory):
        print(f"[pdf_loader] directory not found: {directory}")
        return documents

    for filename in os.listdir(directory):
        if not filename.lower().endswith(".pdf"):
            continue
        path = os.path.join(directory, filename)
        try:
            doc = fitz.open(path)
            raw_text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception as e:
            print(f"[pdf_loader] failed to read {filename}: {e}")
            continue

        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        documents.append({
            "source_type": "pdf",
            "source_ref": path,
            "title": filename,
            "raw_text": raw_text,
            "content_hash": content_hash,
        })
    return documents

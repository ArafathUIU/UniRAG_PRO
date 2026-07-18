"""
Loads documents added through the admin API/UI from ADMIN_UPLOAD_DIR.

These files are stored on disk (not just in the vector DB) so the scheduled
pipeline — which wipes and rebuilds the whole ChromaDB collection on each run —
re-ingests them and they survive. Text extraction reuses rag.file_processor so
every file type the chat upload supports (PDF, DOC/DOCX, images via vision,
TXT/CSV/MD, and a generic text fallback) works here too.
"""
import hashlib
import os

from rag.file_processor import extract_text_from_file


def _source_type_for(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        return "pdf"
    if ext in ("png", "jpg", "jpeg", "webp", "bmp", "gif"):
        return "image"
    if ext in ("doc", "docx"):
        return "doc"
    return "text"


def load_one_file(path: str) -> dict | None:
    """Extracts and normalizes a single file on disk into a document dict."""
    filename = os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            raw_text = extract_text_from_file(fh, filename)
    except Exception as e:
        print(f"[admin_loader] failed to read {filename}: {e}")
        return None

    if not raw_text or not raw_text.strip():
        print(f"[admin_loader] no extractable text in {filename}, skipping")
        return None

    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return {
        "source_type": _source_type_for(filename),
        "source_ref": path,
        "title": filename,
        "raw_text": raw_text,
        "content_hash": content_hash,
    }


def load_admin_uploads(directory: str) -> list[dict]:
    """Loads every file in the admin upload directory as a document dict."""
    documents = []
    if not os.path.isdir(directory):
        return documents

    for filename in sorted(os.listdir(directory)):
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        doc = load_one_file(path)
        if doc:
            documents.append(doc)
    return documents

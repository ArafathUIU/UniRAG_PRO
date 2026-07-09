from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=120,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def chunk_document(document: dict) -> list[dict]:
    """Splits one loaded document into chunks, keeping source metadata attached."""
    pieces = splitter.split_text(document["raw_text"])
    chunks = []
    for i, piece in enumerate(pieces):
        chunks.append({
            "text": piece,
            "chunk_index": i,
            "source_type": document["source_type"],
            "source_ref": document["source_ref"],
            "title": document["title"],
            "content_hash": document["content_hash"],
        })
    return chunks

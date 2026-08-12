from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rag.router import chat_graph
from rag.vectorstore import get_last_updated, get_source_count
from rag.file_processor import extract_text_from_files
from ingestion.admin_service import (
    list_documents,
    add_document_from_file,
    add_document_from_text,
    delete_document,
)
from api.auth import require_admin_password

# Header carrying the shared admin password, surfaced in Swagger for all
# admin operations.
ADMIN_AUTH_HEADER = OpenApiParameter(
    name="X-Admin-Password",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Shared admin password (settings.ADMIN_PASSWORD).",
)
from api.serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    StatusResponseSerializer,
    ErrorSerializer,
    AdminDocumentListSerializer,
    AdminAddDocumentSerializer,
    AdminAddResultSerializer,
    AdminDeleteResultSerializer,
)


@extend_schema(
    request=ChatRequestSerializer,
    responses={
        200: ChatResponseSerializer,
        400: ErrorSerializer,
        500: ErrorSerializer,
    },
    summary="Send a chat message",
    description="Send a question (and/or a file) to the RAG chatbot. "
    "Either `message` or `file` is required.",
)
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def chat(request):
    query = request.data.get("message", "").strip()
    session_id = request.data.get("session_id", "default").strip() or "default"
    
    # Accept multiple files under "files"; fall back to a single "file" field.
    files = request.FILES.getlist("files")
    if not files:
        single = request.FILES.get("file")
        if single:
            files = [single]

    file_name = None
    file_text = None
    if files:
        file_name, file_text = extract_text_from_files(files)

    if not query and not file_text:
        return Response({"error": "message or file is required"}, status=400)

    # If query is empty but file(s) are attached, set a default query
    if not query and file_text:
        query = f"Please summarize key information from {file_name}"

    try:
        result = chat_graph.invoke({
            "session_id": session_id,
            "query": query,
            "intent": "",
            "context": "",
            "answer": "",
            "chat_history": "",
            "conversation_summary": "",
            "file_name": file_name,
            "file_text": file_text,
        })
        return Response({
            "answer": result["answer"],
            "intent": result["intent"],
            "session_id": session_id,
        })
    except Exception as e:
        return Response({
            "error": f"LLM / Graph execution error: {str(e)}"
        }, status=500)


@extend_schema(
    responses={200: StatusResponseSerializer},
    summary="Knowledge base status",
    description="Returns the last ingestion timestamp and the number of indexed sources.",
)
@api_view(["GET"])
def status(request):
    last_updated = get_last_updated()
    return Response({
        "last_updated": last_updated.isoformat() if last_updated else None,
        "source_count": get_source_count(),
    })


@extend_schema(
    methods=["GET"],
    parameters=[ADMIN_AUTH_HEADER],
    responses={200: AdminDocumentListSerializer, 401: ErrorSerializer},
    summary="List knowledge base documents",
    description="Returns every indexed source with its type, title, chunk count, and last-updated time. "
    "Requires the admin password.",
)
@extend_schema(
    methods=["POST"],
    parameters=[ADMIN_AUTH_HEADER],
    request=AdminAddDocumentSerializer,
    responses={201: AdminAddResultSerializer, 400: ErrorSerializer, 401: ErrorSerializer},
    summary="Add a knowledge base document",
    description="Upload a file (multipart 'file') OR add raw text ('title' + 'text'). "
    "The document is chunked, embedded, and stored in the vector database immediately. "
    "Requires the admin password.",
)
@extend_schema(
    methods=["DELETE"],
    parameters=[
        ADMIN_AUTH_HEADER,
        OpenApiParameter(
            name="source_ref", type=str, location=OpenApiParameter.QUERY, required=True,
            description="source_ref of the document to delete (from the list endpoint).",
        ),
    ],
    responses={200: AdminDeleteResultSerializer, 400: ErrorSerializer, 401: ErrorSerializer},
    summary="Delete a knowledge base document",
    description="Removes the document's vectors from ChromaDB and deletes its file "
    "so it will not be re-ingested. Requires the admin password.",
)
@api_view(["GET", "POST", "DELETE"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@require_admin_password
def admin_documents(request):
    # --- List ---
    if request.method == "GET":
        docs = list_documents()
        return Response({"documents": docs, "count": len(docs)})

    # --- Delete ---
    if request.method == "DELETE":
        source_ref = request.query_params.get("source_ref") or request.data.get("source_ref")
        if not source_ref:
            return Response({"error": "source_ref is required"}, status=400)
        try:
            return Response(delete_document(source_ref))
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    # --- Add (file upload or pasted text) ---
    file_obj = request.FILES.get("file")
    if file_obj:
        try:
            return Response(add_document_from_file(file_obj, file_obj.name), status=201)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    text = (request.data.get("text") or "").strip()
    if text:
        title = (request.data.get("title") or "").strip()
        try:
            return Response(add_document_from_text(title, text), status=201)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    return Response({"error": "Provide a 'file' to upload or 'text' to add."}, status=400)

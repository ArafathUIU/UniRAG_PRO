from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
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
    responses={200: ChatResponseSerializer, 400: ErrorSerializer, 500: ErrorSerializer},
    summary="Send a chat message",
    description="Send a question (and/or a file) to the RAG chatbot.",
)
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@throttle_classes([AnonRateThrottle, UserRateThrottle])
def chat(request):
    query = request.data.get("message", "").strip()
    session_id = request.data.get("session_id", "default").strip() or "default"
    files = request.FILES.getlist("files")
    if not files:
        single = request.FILES.get("file")
        if single:
            files = [single]
    file_name, file_text = None, None
    if files:
        file_name, file_text = extract_text_from_files(files)
    if not query and not file_text:
        return Response({"error": "message or file is required"}, status=400)
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
        return Response({"error": f"LLM execution error: {str(e)}"}, status=500)

@extend_schema(
    responses={200: StatusResponseSerializer},
    summary="Knowledge base status",
)
@api_view(["GET"])
def status(request):
    last_updated = get_last_updated()
    return Response({
        "last_updated": last_updated.isoformat() if last_updated else None,
        "source_count": get_source_count(),
    })

@api_view(["GET", "POST", "DELETE"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
@require_admin_password
def admin_documents(request):
    if request.method == "GET":
        docs = list_documents()
        return Response({"documents": docs, "count": len(docs)})
    if request.method == "DELETE":
        source_ref = request.query_params.get("source_ref") or request.data.get("source_ref")
        if not source_ref:
            return Response({"error": "source_ref is required"}, status=400)
        try:
            return Response(delete_document(source_ref))
        except Exception as e:
            return Response({"error": str(e)}, status=400)
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
    return Response({"error": "Provide a 'file' or 'text'."}, status=400)

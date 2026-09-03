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

@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def chat_stream(request):
    import json
    import logging
    from django.http import StreamingHttpResponse
    from django.conf import settings
    from rag.router import _fast_reply, _extract_text_content
    from rag.retriever import retrieve_context
    from rag.memory import get_conversation_summary, format_history_text, add_turn

    logger = logging.getLogger(__name__)

    query = request.data.get("message", "").strip()
    session_id = request.data.get("session_id", "default").strip() or "default"

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

    if not query and file_text:
        query = f"Please summarize key information from {file_name}"

    def event_generator():
        fast = _fast_reply(query)
        if fast is not None:
            add_turn(session_id, query, fast)
            yield f"data: {json.dumps({'content': fast, 'intent': 'GREETING', 'done': True})}\n\n"
            return

        summary = get_conversation_summary(session_id)
        history = format_history_text(session_id)

        context = ""
        if not file_text:
            try:
                context = retrieve_context(query=query, conversation_summary=summary, chat_history=history)
            except Exception as e:
                logger.warning(f"Context retrieval error: {e}")
                context = ""

        if context:
            prompt = (
                "You are an expert university knowledge assistant for Bangladeshi universities.\n"
                "Using the retrieved context below and prior conversation summary, answer the user's question accurately.\n\n"
                "CRITICAL RESPONSE FORMATTING RULES:\n"
                "1. Use natural, standard English with normal spacing between every word.\n"
                "2. Write clear, well-structured paragraphs, bullet points, or clean Markdown tables.\n"
                "3. Do NOT compress words together or omit spaces.\n"
                "4. Bold key facts, university names, locations, GPA requirements, tuition fees, and dates.\n\n"
            )
            if summary or history:
                prompt += f"Prior Context:\n{summary}\n{history}\n\n"
            prompt += f"Context:\n{context}\n\n"
        else:
            prompt = (
                "You are an expert university knowledge assistant for Bangladeshi universities.\n"
                "Answer the user's question accurately, directly, and helpfully regarding Bangladeshi higher education.\n\n"
                "CRITICAL RESPONSE FORMATTING RULES:\n"
                "1. Use natural, standard English with normal spacing between every word.\n"
                "2. Write clear, well-structured paragraphs, bullet points, or clean Markdown tables.\n"
                "3. Bold key facts, university names, locations, GPA requirements, tuition fees, and dates.\n\n"
            )
            if summary or history:
                prompt += f"Prior Context:\n{summary}\n{history}\n\n"
        if file_text:
            prompt += f"Attached File Content ({file_name}):\n{file_text[:8000]}\n\n"
        prompt += f"User Question: {query}\n\nAnswer:"

        gemini_key = getattr(settings, "GEMINI_API_KEY", None)
        groq_key = getattr(settings, "GROQ_API_KEY", None)

        full_answer = ""
        intent = "ATTACHED_FILE" if file_text else "KNOWLEDGE"
        yield f"data: {json.dumps({'intent': intent, 'done': False})}\n\n"

        stream_success = False

        if gemini_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    model=getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash"),
                    google_api_key=gemini_key,
                    temperature=0.3,
                    max_retries=0,
                    streaming=True
                )
                for chunk in llm.stream(prompt):
                    text = _extract_text_content(chunk.content)
                    if text:
                        full_answer += text
                        yield f"data: {json.dumps({'content': text, 'done': False})}\n\n"
                stream_success = True
            except Exception as e:
                logger.warning(f"Gemini streaming failed: {e}. Attempting Groq fallback...")

        if not stream_success and groq_key:
            try:
                from langchain_groq import ChatGroq
                llm = ChatGroq(model=getattr(settings, "GROQ_MODEL", "openai/gpt-oss-20b"), api_key=groq_key, temperature=0.3, streaming=True)
                for chunk in llm.stream(prompt):
                    text = _extract_text_content(chunk.content)
                    if text:
                        full_answer += text
                        yield f"data: {json.dumps({'content': text, 'done': False})}\n\n"
                stream_success = True
            except Exception as e:
                logger.warning(f"Groq streaming failed: {e}")

        if not stream_success and not full_answer:
            full_answer = "⚠️ LLM Streaming unavailable. Please check your API quota or keys."
            yield f"data: {json.dumps({'content': full_answer, 'done': False})}\n\n"

        add_turn(session_id, query, full_answer)
        yield f"data: {json.dumps({'done': True})}\n\n"

    response = StreamingHttpResponse(event_generator(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response

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

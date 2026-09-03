from django.urls import path
from api.views import chat, chat_stream, status, admin_documents

urlpatterns = [
    path("chat/", chat, name="chat"),
    path("chat/stream/", chat_stream, name="chat-stream"),
    path("status/", status, name="status"),
    path("admin/documents/", admin_documents, name="admin-documents"),
]

from django.urls import path
from api.views import chat, status, admin_documents

urlpatterns = [
    path("chat/", chat, name="chat"),
    path("status/", status, name="status"),
    path("admin/documents/", admin_documents, name="admin-documents"),
]

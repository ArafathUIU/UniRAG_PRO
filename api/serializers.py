from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="User question. Required unless a file is attached.",
    )
    session_id = serializers.CharField(
        required=False,
        default="default",
        help_text="Conversation session id for memory/context continuity.",
    )
    files = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        help_text="One or more files of any type (PDF, DOC/DOCX, images, "
        "TXT/CSV/MD, etc.). Multiple files can be uploaded at once.",
    )
    file = serializers.FileField(
        required=False,
        help_text="Deprecated single-file field, kept for backward "
        "compatibility. Prefer 'files'.",
    )


class ChatResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    intent = serializers.CharField()
    session_id = serializers.CharField()


class StatusResponseSerializer(serializers.Serializer):
    last_updated = serializers.DateTimeField(allow_null=True)
    source_count = serializers.IntegerField()


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()


# --- Admin knowledge base management ---

class AdminDocumentSerializer(serializers.Serializer):
    source_ref = serializers.CharField(help_text="Stable identifier (file path or URL) of the source.")
    source_type = serializers.CharField(help_text="pdf, image, doc, text, or web.")
    title = serializers.CharField(help_text="Human-readable title / filename.")
    chunk_count = serializers.IntegerField(help_text="Number of indexed chunks for this source.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO timestamp of last indexing.")


class AdminDocumentListSerializer(serializers.Serializer):
    documents = AdminDocumentSerializer(many=True)
    count = serializers.IntegerField()


class AdminAddDocumentSerializer(serializers.Serializer):
    file = serializers.FileField(
        required=False,
        help_text="A document to upload (PDF, DOC/DOCX, image, TXT/CSV/MD, etc.). "
        "Provide this OR 'text'.",
    )
    title = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Title for pasted text (used as the filename).",
    )
    text = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Raw text to add directly. Provide this OR 'file'.",
    )


class AdminAddResultSerializer(serializers.Serializer):
    source_ref = serializers.CharField()
    title = serializers.CharField()
    source_type = serializers.CharField()
    chunk_count = serializers.IntegerField()


class AdminDeleteResultSerializer(serializers.Serializer):
    source_ref = serializers.CharField()
    removed_file = serializers.BooleanField()

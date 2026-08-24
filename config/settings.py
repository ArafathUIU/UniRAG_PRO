import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "api",
    "ingestion",
    "rag",
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "UniRAG API",
    "DESCRIPTION": "Bangladeshi University Admissions RAG Chatbot — chat and status endpoints.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

STATIC_URL = "static/"

# --- Celery ---
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_TIMEZONE = "Asia/Dhaka"

# --- Knowledge base sources ---
# Web URLs to scrape live in knowledge_base/web_sources.txt — one URL per
# line, '#' for comments. Add or remove URLs there any time, no code changes
# or rebuild needed; the next ingestion run (scheduled or manual) picks up
# the current contents of the file automatically.
WEB_SOURCES_FILE = os.getenv(
    "WEB_SOURCES_FILE",
    os.path.join(BASE_DIR, "knowledge_base", "web_sources.txt"),
)
PDF_SOURCE_DIR = os.getenv("PDF_SOURCE_DIR", "./knowledge_base/pdfs")

# Documents added through the admin API/UI are stored here so they persist and
# are re-ingested by the scheduled pipeline (which rebuilds the whole store on
# each run). Delete via the admin API removes both the file and its vectors.
ADMIN_UPLOAD_DIR = os.getenv(
    "ADMIN_UPLOAD_DIR",
    os.path.join(BASE_DIR, "knowledge_base", "admin_uploads"),
)

# --- Vector store (ChromaDB, persistent SQLite-backed, fully local) ---
CHROMA_PERSIST_DIR = os.getenv(
    "CHROMA_PERSIST_DIR",
    os.path.join(BASE_DIR, "chroma_store"),
)

# --- Chat LLM (Groq) ---
# openai/gpt-oss-20b is Groq's current recommended fast/cheap production
# model (as of July 2026). If you want higher quality at more cost, use
# openai/gpt-oss-120b — see https://console.groq.com/docs/models for the
# current list.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

# --- Admin knowledge base management ---
# Shared password protecting the /manage/ UI and the /admin/documents/ API.
# Set a strong value in .env for any real deployment.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "unirag-admin")

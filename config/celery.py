import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("rag_chatbot")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Runs every day at 3:00 AM Asia/Dhaka — pick whatever time makes sense
app.conf.beat_schedule = {
    "daily-knowledge-base-refresh": {
        "task": "ingestion.tasks.refresh_knowledge_base",
        "schedule": crontab(hour=3, minute=0),
    },
}

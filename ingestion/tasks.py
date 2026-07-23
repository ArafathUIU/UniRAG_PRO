from celery import shared_task
from ingestion.pipeline import run_ingestion


@shared_task
def refresh_knowledge_base():
    run_ingestion()

"""Run as a separate Render worker: python -m bookrag_cloud.worker."""
import logging
import time

from .config import settings
from .ingestion import ingest_document
from .providers import HostedModels
from .repository import Repository
from .storage import PrivateStorage

log = logging.getLogger(__name__)


def work_once(repo: Repository, storage: PrivateStorage, models: HostedModels, cfg) -> bool:
    repo.fail_exhausted_jobs()
    job = repo.claim_job()
    if not job:
        return False
    document = repo.job_document(job["document_id"])
    if not document:
        return True
    try:
        ingest_document(document, repo, storage, models, cfg)
    except Exception:
        # The database stores a safe message. Details remain only in the private worker log.
        log.exception("Ingestion failed for document %s", job["document_id"])
        repo.job_failure(job["document_id"], job["attempts"], "Could not process this PDF")
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    cfg = settings()
    if not all((cfg.database_url, cfg.supabase_url, cfg.supabase_service_role_key, cfg.voyage_api_key)):
        raise RuntimeError("Worker configuration is incomplete")
    repo, storage, models = Repository(cfg.database_url), PrivateStorage(cfg), HostedModels(cfg)
    while True:
        if not work_once(repo, storage, models, cfg):
            time.sleep(cfg.worker_poll_seconds)


if __name__ == "__main__":
    main()

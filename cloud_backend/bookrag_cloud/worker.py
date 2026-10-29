"""Run as a separate Render worker: python -m bookrag_cloud.worker."""
import logging
import time

from .config import settings
from .chunking import PasswordProtectedPdfError
from .ingestion import ingest_document
from .providers import HostedModels, ProviderRejected
from .repository import LostJobLease, Repository, UncertainEmbeddingBatch
from .storage import PrivateStorage

log = logging.getLogger(__name__)


def work_once(repo: Repository, storage: PrivateStorage, models: HostedModels, cfg) -> bool:
    repo.flag_stale_pending()
    repo.fail_exhausted_jobs()
    job = repo.claim_job()
    if not job:
        return False
    document = repo.job_document(job["document_id"])
    if not document:
        return True
    try:
        ingest_document(document, job["claim_token"], repo, storage, models, cfg)
    except LostJobLease:
        log.warning("Job lease changed for document %s", job["document_id"])
    except UncertainEmbeddingBatch:
        repo.flag_uncertain_job(job["document_id"], job["claim_token"])
    except PasswordProtectedPdfError:
        repo.job_failure(job["document_id"], job["claim_token"], 3,
                         "This PDF requires a password. Upload an unlocked copy.")
    except ProviderRejected as exc:
        attempts = 3 if exc.status_code != 429 else job["attempts"]
        repo.job_failure(job["document_id"], job["claim_token"], attempts,
                         "Embedding provider rate limit" if exc.status_code == 429 else "Embedding provider rejected the request")
    except Exception:
        # Timeout/5xx after dispatch is ambiguous: preserve pending and stop automatic retry.
        log.exception("Ingestion failed for document %s", job["document_id"])
        if repo.has_pending_batch(job["document_id"]):
            repo.flag_uncertain_job(job["document_id"], job["claim_token"])
        else:
            repo.job_failure(job["document_id"], job["claim_token"], job["attempts"], "Could not process this PDF")
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

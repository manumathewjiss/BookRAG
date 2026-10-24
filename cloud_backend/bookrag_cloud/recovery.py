"""Operator-only recovery. Never exposed over HTTP and never calls providers."""
import argparse
from uuid import UUID

from .config import settings
from .repository import Repository


def main():
    parser = argparse.ArgumentParser(description="Recover a BookRAG ingestion job after human review")
    sub = parser.add_subparsers(dest="command", required=True)
    retry = sub.add_parser("retry-failed", help="Retry a definite failure; reuse saved successful batches")
    retry.add_argument("document_id", type=UUID)
    clear = sub.add_parser("clear-uncertain", help="Clear one pending batch only after checking provider usage")
    clear.add_argument("document_id", type=UUID)
    clear.add_argument("batch_index", type=int)
    clear.add_argument("--confirmed-not-processed", action="store_true", required=True)
    args = parser.parse_args()
    if not settings().database_url:
        parser.error("DATABASE_URL is required")
    repo = Repository(settings().database_url)
    if args.command == "retry-failed":
        changed = repo.retry_failed_job(args.document_id)
    else:
        changed = repo.clear_reviewed_batch(args.document_id, args.batch_index)
    print("Job queued for retry" if changed else "No eligible job or batch; nothing changed")


if __name__ == "__main__":
    main()

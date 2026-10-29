from contextlib import contextmanager
from uuid import uuid4

import pytest

from bookrag_cloud.repository import Repository, UsageLimitReached


class Result:
    def __init__(self, row=None): self.row = row
    def fetchone(self): return self.row


class Connection:
    def __init__(self, totals): self.totals, self.queries = totals, []
    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if "as recent_questions" in sql: return Result(self.totals)
        if "operation='upload'" in sql: return Result({"n": self.totals.get("uploads", 0)})
        if "returning id" in sql: return Result({"id": uuid4()})
        return Result()


def repository_with_connection(connection):
    repo = Repository("unused")
    @contextmanager
    def fake(): yield connection
    repo.connection = fake
    return repo


@pytest.mark.parametrize("totals", [
    {"questions": 50, "recent_questions": 0, "usd": 0},
    {"questions": 0, "recent_questions": 10, "usd": 0},
    {"questions": 0, "recent_questions": 0, "usd": 4.98},
])
def test_question_limits_refuse_before_reservation(totals):
    conn = Connection(totals)
    repo = repository_with_connection(conn)
    assert repo.reserve_question(uuid4(), uuid4(), 50, 5.0, 0.05, 10) is None
    assert any("pg_advisory_xact_lock" in query for query, _ in conn.queries)
    assert not any("insert into usage_events" in query for query, _ in conn.queries)


def test_upload_limit_checked_inside_serialized_transaction():
    conn = Connection({"uploads": 5})
    repo = repository_with_connection(conn)
    with pytest.raises(UsageLimitReached):
        repo.create_document(uuid4(), uuid4(), "Title", "a.pdf", "path", "digest", 5)
    assert any("pg_advisory_xact_lock" in query for query, _ in conn.queries)
    assert not any("insert into documents" in query for query, _ in conn.queries)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class Document(BaseModel):
    id: UUID
    is_sample: bool = False
    title: str
    filename: str
    status: str
    page_count: int = 0
    passage_count: int = 0
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=8, max_length=1200)


class Citation(BaseModel):
    passage_id: UUID
    pdf_page: int
    excerpt: str


class Timings(BaseModel):
    search: int
    rerank: int
    answer: int


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: float = 0.0


class Answer(BaseModel):
    answer: str
    enough_evidence: bool
    evidence_status: str
    citations: list[Citation]
    timings_ms: Timings
    usage: Usage
    reused_answer: bool = False

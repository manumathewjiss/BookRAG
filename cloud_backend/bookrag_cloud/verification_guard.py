"""Request-level limits for the optional real-service verification run."""
from __future__ import annotations

import tiktoken

from .providers import HostedModels


class VerificationLimitReached(RuntimeError):
    pass


class GuardedModels:
    """Reserve conservative list-price cost before each call; never retry implicitly.

    This guard is for a small verification run, not a billing hard stop. Provider
    dashboards may report different billable token counts or cached-token prices.
    """

    def __init__(self, delegate: HostedModels, *, max_voyage_requests: int = 5,
                 max_openai_requests: int = 2, max_voyage_usd: float = 0.02,
                 max_openai_usd: float = 0.10):
        self.delegate = delegate
        self.max_voyage_requests = max_voyage_requests
        self.max_openai_requests = max_openai_requests
        self.max_voyage_usd = max_voyage_usd
        self.max_openai_usd = max_openai_usd
        self.voyage_requests = 0
        self.openai_requests = 0
        self.voyage_reserved_usd = 0.0
        self.openai_reserved_usd = 0.0
        self.codec = tiktoken.get_encoding("cl100k_base")

    def _tokens(self, value: str) -> int:
        return len(self.codec.encode(value))

    def _reserve(self, provider: str, estimated_usd: float):
        if provider == "voyage":
            if (self.voyage_requests >= self.max_voyage_requests
                    or self.voyage_reserved_usd + estimated_usd > self.max_voyage_usd):
                raise VerificationLimitReached("Voyage verification limit reached")
            self.voyage_requests += 1
            self.voyage_reserved_usd += estimated_usd
        else:
            if (self.openai_requests >= self.max_openai_requests
                    or self.openai_reserved_usd + estimated_usd > self.max_openai_usd):
                raise VerificationLimitReached("OpenAI verification limit reached")
            self.openai_requests += 1
            self.openai_reserved_usd += estimated_usd

    def embed(self, texts: list[str], mode: str):
        if not texts or mode not in ("document", "query"):
            raise ValueError("Invalid verification embedding request")
        # 2x input estimate, covering provider tokenization and request overhead.
        estimate = 2 * sum(self._tokens(t) + 8 for t in texts) * .12 / 1_000_000
        self._reserve("voyage", estimate)
        return self.delegate.embed(texts, mode)

    def rerank(self, question: str, passages: list[dict]):
        if passages:
            estimate = 2 * sum(self._tokens(question) + self._tokens(p["text"]) + 16
                               for p in passages) * .05 / 1_000_000
            self._reserve("voyage", estimate)
        return self.delegate.rerank(question, passages)

    def answer(self, question: str, passages: list[dict]):
        # Reserve 2x estimated input plus the full 1024-token output limit.
        input_tokens = self._tokens(question) + sum(self._tokens(p["text"]) + 64 for p in passages) + 400
        estimate = (2 * input_tokens * 2 + 1024 * 10) / 1_000_000
        self._reserve("openai", estimate)
        return self.delegate.answer(question, passages)

    def summary(self) -> dict:
        return {"voyage_requests": self.voyage_requests,
                "openai_requests": self.openai_requests,
                "voyage_reserved_usd": round(self.voyage_reserved_usd, 6),
                "openai_reserved_usd": round(self.openai_reserved_usd, 6)}

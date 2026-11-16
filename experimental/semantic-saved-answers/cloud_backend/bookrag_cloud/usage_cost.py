"""Per-call cost estimates for one chat request.

Published rates below are the ones already recorded for this project
(Voyage list price and gpt-6.1-sol Standard, checked 26 Oct 2026).
gpt-6-luna has no published rate in this repository. Verification calls
are therefore priced at the gpt-6.1-sol rates so a daily spend cap cannot
be under-counted. That figure is a protective estimate, not a provider invoice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# USD per million tokens: (input, output).
PUBLISHED_USD_PER_MILLION = {
    "voyage-4-large": (0.12, 0.0),
    "rerank-3": (0.05, 0.0),
    "gpt-6.1-sol": (2.0, 10.0),
}

CONSERVATIVE_UNPRICED_MODEL = "gpt-6.1-sol"


@dataclass
class UsageComponent:
    component: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: float = 0.0
    certainty: str = "known"
    rate_source: str = "published"
    attempt: int = 1

    def as_dict(self) -> dict:
        return {
            "component": self.component,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": self.estimated_usd,
            "certainty": self.certainty,
            "rate_source": self.rate_source,
            "attempt": self.attempt,
        }


def estimate_usd(provider: str, input_tokens: int, output_tokens: int) -> tuple[float, str]:
    rates = PUBLISHED_USD_PER_MILLION.get(provider)
    source = "published"
    if rates is None:
        rates = PUBLISHED_USD_PER_MILLION[CONSERVATIVE_UNPRICED_MODEL]
        source = "conservative_sol_stand_in"
    usd = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
    return round(usd, 6), source


@dataclass
class UsageLedger:
    components: list[UsageComponent] = field(default_factory=list)

    def add(
        self,
        component: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        *,
        certainty: str = "known",
        attempt: int = 1,
    ) -> UsageComponent:
        usd, source = estimate_usd(provider, input_tokens, output_tokens)
        if certainty == "unbilled_failure":
            usd = 0.0
        row = UsageComponent(
            component=component,
            provider=provider,
            input_tokens=max(0, int(input_tokens)),
            output_tokens=max(0, int(output_tokens)),
            estimated_usd=usd,
            certainty=certainty,
            rate_source=source,
            attempt=attempt,
        )
        self.components.append(row)
        return row

    @property
    def certainty(self) -> str:
        if any(row.certainty == "uncertain" for row in self.components):
            return "uncertain"
        return "known"

    def known_usd(self) -> float:
        return round(
            sum(row.estimated_usd for row in self.components if row.certainty != "unbilled_failure"),
            6,
        )

    def settle_usd(self, reserve_usd: float) -> float:
        """Known totals replace the $0.05 hold.

        An uncertain attempt that returned no token counts keeps one hold per such
        attempt, added to the known lines. An uncertain attempt that did return
        tokens keeps the hold only when it is higher than the known total.
        """
        known = self.known_usd()
        unknown_attempts = sum(
            1 for row in self.components
            if row.certainty == "uncertain" and row.input_tokens == 0 and row.output_tokens == 0
        )
        if unknown_attempts:
            return round(known + float(reserve_usd) * unknown_attempts, 6)
        if self.certainty == "uncertain":
            return round(max(known, float(reserve_usd)), 6)
        return known

    def input_tokens(self) -> int:
        return sum(row.input_tokens for row in self.components if row.certainty != "unbilled_failure")

    def output_tokens(self) -> int:
        return sum(row.output_tokens for row in self.components if row.certainty != "unbilled_failure")

    def as_list(self) -> list[dict]:
        return [row.as_dict() for row in self.components]

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Posting:
    source: str          # "workday" | "greenhouse"
    employer: str
    external_id: str     # stable, unique per employer requisition
    title: str
    location: str
    url: str
    detail_path: str = ""
    posted_text: str = ""
    description: str = ""

    # Source-specific facts used before scoring but never stored (Reed's
    # summary and salary feed the first-pass check). Not a description.
    extra: dict = field(default_factory=dict)

    # populated by the scoring stage
    score: int | None = None
    verdict: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"

    def __str__(self) -> str:  # for logs
        return f"[{self.employer}] {self.title} ({self.location})"

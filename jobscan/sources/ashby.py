"""Ashby adapter.

Ashby's job boards are JavaScript-rendered, so fetching the page HTML gets you
an empty shell. The posting API behind them is public and returns everything
in one call, which avoids needing a headless browser:

    GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterator

import requests

from ..models import Posting
from ..net import make_session

USES_QUERY = False

UA = "jobscan/0.1"


@dataclass
class AshbyEmployer:
    name: str
    board: str


def _clean(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def search(emp: AshbyEmployer, session: requests.Session | None = None) -> Iterator[Posting]:
    s = session or make_session()
    resp = s.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{emp.board}",
        params={"includeCompensation": "true"},
        headers={"Accept": "application/json", "User-Agent": UA},
        timeout=30,
    )
    resp.raise_for_status()

    for item in resp.json().get("jobs", []):
        # descriptionPlain is provided already stripped; descriptionHtml is the
        # fallback when a posting was authored in the rich editor.
        desc = item.get("descriptionPlain") or _clean(item.get("descriptionHtml", ""))
        yield Posting(
            source="ashby",
            employer=emp.name,
            external_id=f"{emp.board}:{item.get('id')}",
            title=(item.get("title") or "").strip(),
            location=(item.get("location") or "").strip(),
            url=item.get("jobUrl") or item.get("applyUrl") or "",
            posted_text=(item.get("publishedAt") or "")[:10],
            description=desc,
        )


def fetch_description(emp, posting: Posting, session=None) -> str:
    return posting.description


# is_alive() is False only when the whole board was fetched and the id is not on it, so a False here is a
# definitive withdrawal: the role closes on the first reading.
DEFINITIVE_GONE = True


def is_alive(emp: AshbyEmployer, posting: Posting, session=None) -> bool:
    """Ashby has no per-posting endpoint on the public API, so liveness is
    decided by whether the id is still on the board."""
    s = session or make_session()
    job_id = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{emp.board}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return True  # never call a role dead because the network wobbled
    return any(str(j.get("id")) == job_id for j in resp.json().get("jobs", []))

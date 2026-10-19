"""Greenhouse adapter.

Greenhouse publishes a documented public JSON board API, so this one needs no
reverse engineering:

    GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true

`content=true` returns the full HTML description in the same call, so unlike
Workday there is no second fetch per posting.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterator

import requests

from ..net import make_session

from ..models import Posting

USES_QUERY = False  # the board API returns everything in one call

UA = "jobscan/0.1"


@dataclass
class GreenhouseEmployer:
    name: str
    board: str


def _clean_html(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def search(
    emp: GreenhouseEmployer, session: requests.Session | None = None
) -> Iterator[Posting]:
    """Greenhouse has no server-side search, so pull the whole board and let
    the local filter do the work. Boards are small enough for this."""
    s = session or make_session()
    resp = s.get(
        f"https://boards-api.greenhouse.io/v1/boards/{emp.board}/jobs",
        params={"content": "true"},
        headers={"Accept": "application/json", "User-Agent": UA},
        timeout=30,
    )
    resp.raise_for_status()

    for item in resp.json().get("jobs", []):
        yield Posting(
            source="greenhouse",
            employer=emp.name,
            external_id=f"{emp.board}:{item['id']}",
            title=(item.get("title") or "").strip(),
            location=((item.get("location") or {}).get("name") or "").strip(),
            url=item.get("absolute_url", ""),
            posted_text=(item.get("updated_at") or "")[:10],
            description=_clean_html(item.get("content", "")),
        )


def fetch_description(emp, posting: Posting, session=None) -> str:
    return posting.description  # already have it


# is_alive() is False only on an explicit 404/410 from the board API, so a False here is a
# definitive withdrawal: the role closes on the first reading.
DEFINITIVE_GONE = True


def is_alive(emp: GreenhouseEmployer, posting: Posting, session=None) -> bool:
    s = session or make_session()
    job_id = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"https://boards-api.greenhouse.io/v1/boards/{emp.board}/jobs/{job_id}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
    except requests.RequestException:
        return True
    return resp.status_code not in (404, 410)

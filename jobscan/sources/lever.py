"""Lever adapter.

    GET https://api.lever.co/v0/postings/{company}?mode=json

Returns the whole board with descriptions inline. Lever splits the body across
`description` (the intro) and `lists` (the bulleted sections), so both have to
be reassembled or the scoring model sees only half the posting.
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
class LeverEmployer:
    name: str
    board: str


def _clean(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _body(item: dict) -> str:
    parts = [_clean(item.get("description", ""))]
    for block in item.get("lists") or []:
        parts.append(_clean(block.get("text", "")))
        parts.append(_clean(block.get("content", "")))
    parts.append(_clean(item.get("additional", "")))
    return "\n\n".join(p for p in parts if p)


def search(emp: LeverEmployer, session: requests.Session | None = None) -> Iterator[Posting]:
    s = session or make_session()
    resp = s.get(
        f"https://api.lever.co/v0/postings/{emp.board}",
        params={"mode": "json"},
        headers={"Accept": "application/json", "User-Agent": UA},
        timeout=30,
    )
    resp.raise_for_status()

    for item in resp.json():
        cats = item.get("categories") or {}
        yield Posting(
            source="lever",
            employer=emp.name,
            external_id=f"{emp.board}:{item.get('id')}",
            title=(item.get("text") or "").strip(),
            location=(cats.get("location") or "").strip(),
            url=item.get("hostedUrl") or item.get("applyUrl") or "",
            posted_text="",
            description=_body(item),
        )


def fetch_description(emp, posting: Posting, session=None) -> str:
    return posting.description


# is_alive() is False only on an explicit 404/410 from the postings API, so a False here is a
# definitive withdrawal: the role closes on the first reading.
DEFINITIVE_GONE = True


def is_alive(emp: LeverEmployer, posting: Posting, session=None) -> bool:
    s = session or make_session()
    job_id = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"https://api.lever.co/v0/postings/{emp.board}/{job_id}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
    except requests.RequestException:
        return True
    return resp.status_code not in (404, 410)

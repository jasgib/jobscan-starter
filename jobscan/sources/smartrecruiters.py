"""SmartRecruiters adapter.

    GET https://api.smartrecruiters.com/v1/companies/{company}/postings

The list endpoint gives titles and locations but NOT the description, so unlike
Greenhouse or Ashby this one needs a second fetch per posting. That is done
lazily in fetch_description(), so the local filter can discard a posting on
title and location before we ever pay for its body.
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
PAGE = 100


@dataclass
class SmartRecruitersEmployer:
    name: str
    board: str


def _clean(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _loc(item: dict) -> str:
    loc = item.get("location") or {}
    bits = [loc.get("city"), loc.get("region"), loc.get("country")]
    return ", ".join(b for b in bits if b)


def search(emp: SmartRecruitersEmployer, session: requests.Session | None = None) -> Iterator[Posting]:
    s = session or make_session()
    offset = 0
    while True:
        resp = s.get(
            f"https://api.smartrecruiters.com/v1/companies/{emp.board}/postings",
            params={"limit": PAGE, "offset": offset},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("content") or []
        if not items:
            return
        for item in items:
            yield Posting(
                source="smartrecruiters",
                employer=emp.name,
                external_id=f"{emp.board}:{item.get('id')}",
                title=(item.get("name") or "").strip(),
                location=_loc(item),
                # NOT item["ref"] - that is the API endpoint and renders as
                # raw JSON in a browser. Build the public careers URL instead.
                url=(item.get("applyUrl")
                     or f"https://jobs.smartrecruiters.com/{emp.board}/{item.get('id')}"),
                posted_text=(item.get("releasedDate") or "")[:10],
                description="",  # fetched lazily, see module docstring
            )
        offset += PAGE
        if offset >= (data.get("totalFound") or 0):
            return


def fetch_description(emp: SmartRecruitersEmployer, posting: Posting, session=None) -> str:
    s = session or make_session()
    job_id = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"https://api.smartrecruiters.com/v1/companies/{emp.board}/postings/{job_id}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    ad = (resp.json().get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
        parts.append(_clean((ad.get(key) or {}).get("text", "")))
    return "\n\n".join(p for p in parts if p)


# is_alive() is False only on an explicit 404/410 from the postings API, so a False here is a
# definitive withdrawal: the role closes on the first reading.
DEFINITIVE_GONE = True


def is_alive(emp: SmartRecruitersEmployer, posting: Posting, session=None) -> bool:
    s = session or make_session()
    job_id = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"https://api.smartrecruiters.com/v1/companies/{emp.board}/postings/{job_id}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
    except requests.RequestException:
        return True
    return resp.status_code not in (404, 410)

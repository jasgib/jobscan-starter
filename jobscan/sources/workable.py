"""Workable - used by Starling Bank, Luminance, Hugging Face and others.

    POST https://apply.workable.com/api/v3/accounts/{account}/jobs   (paged by nextPage token)
    GET  https://apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}

Public, unauthenticated, the same endpoints the hosted careers page calls.
The list carries no description, so it is fetched at scoring time.
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
UA = {"User-Agent": "Mozilla/5.0 (jobscan)", "Accept": "application/json"}
MAX_PAGES = 30          # 10 per page


@dataclass
class WorkableEmployer:
    name: str
    account: str

    @property
    def api(self) -> str:
        return f"https://apply.workable.com/api"


def _clean(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _location(j: dict) -> str:
    locs = j.get("locations") or ([j["location"]] if j.get("location") else [])
    names = [", ".join(x for x in ((l.get("city") or ""), (l.get("country") or "")) if x)
             for l in locs if not l.get("hidden")]
    return " / ".join(n for n in dict.fromkeys(names) if n)


def search(emp: WorkableEmployer, session: requests.Session | None = None) -> Iterator[Posting]:
    s = session or make_session()
    body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
    for _ in range(MAX_PAGES):
        resp = s.post(f"{emp.api}/v3/accounts/{emp.account}/jobs", json=body, headers=UA, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for j in data.get("results") or []:
            code = j.get("shortcode")
            if not code or j.get("state") not in (None, "published"):
                continue
            yield Posting(
                source="workable", employer=emp.name,
                external_id=f"{emp.account}:{code}",
                title=(j.get("title") or "").strip(),
                location=_location(j),
                url=f"https://apply.workable.com/{emp.account}/j/{code}/",
                posted_text=(j.get("published") or "")[:10],
                description="",
            )
        token = data.get("nextPage")
        if not token:
            return
        body["token"] = token


def fetch_description(emp: WorkableEmployer, posting: Posting, session=None) -> str:
    s = session or make_session()
    code = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(f"{emp.api}/v2/accounts/{emp.account}/jobs/{code}", headers=UA, timeout=30)
        resp.raise_for_status()
        d = resp.json()
    except (requests.RequestException, ValueError):
        return ""
    return "\n\n".join(p for p in (_clean(d.get("description", "")), _clean(d.get("requirements", ""))) if p)


# A withdrawn Workable job answers 404 from its own API: definitive.
DEFINITIVE_GONE = True


def is_alive(emp: WorkableEmployer, posting: Posting, session=None) -> bool:
    s = session or make_session()
    code = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(f"{emp.api}/v2/accounts/{emp.account}/jobs/{code}", headers=UA, timeout=30)
    except requests.RequestException:
        return True
    return resp.status_code not in (404, 410)

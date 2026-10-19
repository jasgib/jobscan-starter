"""Eightfold AI adapter.

Eightfold-hosted career portals expose the same JSON API their own front end
calls - the same shape of win as Workday, one adapter for many employers:

    GET {base}/api/apply/v2/jobs?domain={domain}&start=0&num=20&query=credit
    GET {base}/api/apply/v2/jobs/{id}?domain={domain}      # full description

Found by opening the careers site and watching the network tab, exactly as
the README describes for Workday.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterator

import requests

from ..net import make_session

from ..models import Posting

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 jobscan/0.1"
PAGE = 20
MAX_PAGES = 10


@dataclass
class EightfoldEmployer:
    name: str
    base: str      # e.g. https://portal.careers.hsbc.com
    domain: str    # e.g. hsbc.com

    @property
    def api(self) -> str:
        return f"{self.base.rstrip('/')}/api/apply/v2/jobs"


def _clean_html(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw or "")
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
        .replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    )
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def search(
    emp: EightfoldEmployer, query: str, session: requests.Session | None = None
) -> Iterator[Posting]:
    s = session or make_session()
    start = 0

    for _ in range(MAX_PAGES):
        resp = s.get(
            emp.api,
            params={"domain": emp.domain, "start": start, "num": PAGE, "query": query},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()

        positions = data.get("positions") or []
        if not positions:
            return

        for item in positions:
            pid = str(item.get("id") or "")
            locs = item.get("locations") or []
            location = item.get("location") or (locs[0] if locs else "")
            yield Posting(
                source="eightfold",
                employer=emp.name,
                external_id=f"{emp.domain}:{item.get('display_job_id') or pid}",
                title=(item.get("name") or "").strip(),
                location=(location or "").strip(),
                url=item.get("canonicalPositionUrl") or f"{emp.base}/careers/job/{pid}",
                detail_path=pid,
                description=_clean_html(item.get("job_description") or ""),
            )

        start += PAGE
        if start >= (data.get("count") or 0):
            return
        time.sleep(0.4)


def fetch_description(
    emp: EightfoldEmployer, posting: Posting, session: requests.Session | None = None
) -> str:
    s = session or make_session()
    resp = s.get(
        f"{emp.api}/{posting.detail_path}",
        params={"domain": emp.domain},
        headers={"Accept": "application/json", "User-Agent": UA},
        timeout=45,
    )
    resp.raise_for_status()
    body = resp.json()
    if "job_description" not in body:
        body = (body.get("positions") or [{}])[0]
    return _clean_html(body.get("job_description") or "")


def is_alive(
    emp: EightfoldEmployer, posting: Posting, session: requests.Session | None = None
) -> bool:
    s = session or make_session()
    try:
        resp = s.get(
            f"{emp.api}/{posting.detail_path}",
            params={"domain": emp.domain},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=45,
        )
    except requests.RequestException:
        return True  # network blip: assume alive, re-check next run
    if resp.status_code in (404, 410):
        return False
    return resp.status_code < 500

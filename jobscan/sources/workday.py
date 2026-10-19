"""Workday CXS adapter.

Every Workday-hosted careers site exposes the same JSON API that its own
front end calls:

    POST https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "credit"}

and the full description for a posting at:

    GET  https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

Learn it once, get thirty employers.
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
class WorkdayEmployer:
    name: str
    tenant: str
    site: str
    host: str = "wd3"

    @property
    def base(self) -> str:
        return f"https://{self.tenant}.{self.host}.myworkdayjobs.com"

    @property
    def api(self) -> str:
        return f"{self.base}/wday/cxs/{self.tenant}/{self.site}"


def _clean_html(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw or "")
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def search(
    emp: WorkdayEmployer, query: str, session: requests.Session | None = None
) -> Iterator[Posting]:
    """Yield postings matching `query`. Paginates until exhausted."""
    s = session or make_session()
    offset = 0

    for _ in range(MAX_PAGES):
        resp = s.post(
            f"{emp.api}/jobs",
            json={
                "appliedFacets": {},
                "limit": PAGE,
                "offset": offset,
                "searchText": query,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": UA,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()

        listings = data.get("jobPostings", [])
        if not listings:
            return

        for item in listings:
            path = item.get("externalPath", "")
            # bulletFields usually holds the requisition ID, e.g. "JR00098916"
            bullets = item.get("bulletFields") or []
            req_id = bullets[0] if bullets else path.rsplit("_", 1)[-1]

            yield Posting(
                source="workday",
                employer=emp.name,
                external_id=f"{emp.tenant}:{req_id}",
                title=item.get("title", "").strip(),
                location=(item.get("locationsText") or "").strip(),
                url=f"{emp.base}/en-US/{emp.site}{path}",
                detail_path=path,
                posted_text=(item.get("postedOn") or "").strip(),
            )

        offset += PAGE
        if offset >= data.get("total", 0):
            return
        time.sleep(0.4)


def fetch_description(
    emp: WorkdayEmployer, posting: Posting, session: requests.Session | None = None
) -> str:
    """Pull the full JD text. Called only for postings that clear stage 1."""
    s = session or make_session()
    resp = s.get(
        f"{emp.api}{posting.detail_path}",
        headers={"Accept": "application/json", "User-Agent": UA},
        timeout=45,
    )
    resp.raise_for_status()
    info = resp.json().get("jobPostingInfo", {}) or {}
    return _clean_html(info.get("jobDescription", ""))


def is_alive(
    emp: WorkdayEmployer, posting: Posting, session: requests.Session | None = None
) -> bool:
    """True if the requisition is still live. This is the check that would
    have caught the two dead Bank of America roles."""
    s = session or make_session()
    try:
        resp = s.get(
            f"{emp.api}{posting.detail_path}",
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=45,
        )
    except requests.RequestException:
        return True  # network blip: assume alive, re-check next run
    # Anything that could be about us rather than the requisition: assume alive
    # and re-check next run. Marking a live role dead is the worse error - it
    # disappears from the shortlist without a trace.
    if resp.status_code in (401, 403, 429) or resp.status_code >= 500:
        # A withdrawn Workday requisition answers 403 / errorCode S22 - but so
        # does a tenant that is rate-limiting us, and the two are identical on
        # the wire. Treating S22 as proof of withdrawal closed 38 live roles in
        # one night, right after collection had hammered the same tenants eight
        # at a time. So this reports "not seen", and the caller decides: a role
        # is only closed when two consecutive runs agree.
        return False if (resp.status_code == 403 and "S22" in resp.text) else True
    if resp.status_code != 200:
        return False
    # A 200 from the CXS endpoint is not proof: the shell answers 200 for
    # paths that no longer resolve to a posting. Require the actual payload.
    try:
        return bool((resp.json() or {}).get("jobPostingInfo"))
    except ValueError:
        return False

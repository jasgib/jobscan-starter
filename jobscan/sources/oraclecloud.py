"""Oracle Cloud (Fusion) Recruiting adapter.

Used by J.P. Morgan and a number of other large employers whose careers page
is at {tenant}.fa.oraclecloud.com/hcmUI/CandidateExperience.

    GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&finder=findReqs;siteNumber=CX_1,keyword="...",limit=,offset=

Unlike Greenhouse or Ashby this board is enormous - J.P. Morgan alone posts
over 7,000 open requisitions - so pulling it whole on every run would be both
slow and rude. It supports server-side keyword search, so USES_QUERY is True
and the configured queries do the narrowing. Results come back newest-first,
which is what a twice-daily scan wants.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterator

import requests

from ..models import Posting
from ..net import make_session

USES_QUERY = True

UA = "jobscan/0.1"
PAGE = 50
# Newest-first, so the first pages hold anything posted since the last scan.
# Without a cap a single broad query would walk thousands of stale rows.
MAX_PAGES = 4


@dataclass
class OracleEmployer:
    name: str
    host: str                 # e.g. jpmc.fa.oraclecloud.com
    site: str = "CX_1"        # siteNumber

    @property
    def api(self) -> str:
        return f"https://{self.host}/hcmRestApi/resources/latest"


def _clean(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _location(req: dict) -> str:
    primary = (req.get("PrimaryLocation") or "").strip()
    extra = req.get("secondaryLocations") or []
    names = [primary] + [(x.get("LocationName") or "").strip() for x in extra]
    return " / ".join(n for n in dict.fromkeys(names) if n)


def search(emp: OracleEmployer, query: str = "", session: requests.Session | None = None) -> Iterator[Posting]:
    s = session or make_session()
    offset = 0
    for _ in range(MAX_PAGES):
        kw = f',keyword="{query}"' if query else ""
        finder = f"findReqs;siteNumber={emp.site}{kw},limit={PAGE},offset={offset},sortBy=POSTING_DATES_DESC"
        resp = s.get(
            f"{emp.api}/recruitingCEJobRequisitions",
            params={"onlyData": "true",
                    "expand": "requisitionList.secondaryLocations",
                    "finder": finder},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if not items:
            return
        reqs = items[0].get("requisitionList") or []
        if not reqs:
            return
        for req in reqs:
            rid = req.get("Id") or req.get("RequisitionId")
            if not rid:
                continue
            yield Posting(
                source="oraclecloud",
                employer=emp.name,
                external_id=f"{emp.host.split('.')[0]}:{rid}",
                title=(req.get("Title") or "").strip(),
                location=_location(req),
                url=f"https://{emp.host}/hcmUI/CandidateExperience/en/sites/{emp.site}/job/{rid}",
                posted_text=(req.get("PostedDate") or "")[:10],
                description="",   # fetched lazily, see fetch_description
            )
        total = items[0].get("TotalJobsCount") or 0
        offset += PAGE
        if offset >= total:
            return


def fetch_description(emp: OracleEmployer, posting: Posting, session=None) -> str:
    s = session or make_session()
    rid = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"{emp.api}/recruitingCEJobRequisitionDetails",
            params={"expand": "all", "onlyData": "true",
                    "finder": f'ById;Id="{rid}",siteNumber={emp.site}'},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
    except requests.RequestException:
        return ""
    if not items:
        return ""
    d = items[0]
    parts = [_clean(d.get("ExternalDescriptionStr", "")),
             _clean(d.get("ExternalQualificationsStr", "")),
             _clean(d.get("ExternalResponsibilitiesStr", ""))]
    return "\n\n".join(p for p in parts if p)


def is_alive(emp: OracleEmployer, posting: Posting, session=None) -> bool:
    s = session or make_session()
    rid = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(
            f"{emp.api}/recruitingCEJobRequisitionDetails",
            params={"onlyData": "true", "finder": f'ById;Id="{rid}",siteNumber={emp.site}'},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=30,
        )
    except requests.RequestException:
        return True   # never call a role dead because the network wobbled
    if resp.status_code in (404, 410):
        return False
    try:
        return bool(resp.json().get("items"))
    except Exception:  # noqa: BLE001
        return True

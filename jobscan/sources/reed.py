"""Reed.co.uk job search - an aggregator, not an employer.

    GET https://www.reed.co.uk/api/1.0/search?keywords=&locationName=&distanceFromLocation=
        &resultsToTake=100&resultsToSkip=
    GET https://www.reed.co.uk/api/1.0/jobs/{jobId}

The API key goes in HTTP Basic auth as the username with an empty password
(REED_API_KEY in .env). Reed reaches what the employer adapters cannot: roles
posted by recruitment agencies, and employers whose own careers systems
jobscan has no adapter for.

Two things differ from every other source:

- A posting's `employer` is the real advertiser - an employer or an agency -
  not "Reed". So main.module_for() matches Reed postings by SOURCE: matched by
  name, an agency ad for "Barclays" would be routed to the Barclays Workday
  adapter.
- Search results carry only a ~450-character snippet. The description is left
  EMPTY here so the scoring stage fetches the full text, exactly as it does for
  Oracle and Workday; scoring a snippet would judge a role on its first
  paragraph.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterator

import requests

from ..models import Posting
from ..net import make_session

USES_QUERY = True
AGGREGATOR = True
# Job boards return many off-target ads; the /review-jobs command screens
# them from title and summary before reading full descriptions.
TRIAGE = True
SOURCE = "reed"
API = "https://www.reed.co.uk/api/1.0"
PAGE = 100          # Reed's maximum per request
MAX_PAGES = 2


@dataclass
class ReedSource:
    name: str = "Reed"
    location: str = "London"
    distance: int = 10                      # miles
    queries: list[str] = field(default_factory=list)   # overrides search.queries
    min_salary: int = 0       # drop ads whose stated annual maximum is below this (0 = off); no salary = kept
    max_age_days: int = 7     # older ads were either seen already or are stale


def _auth() -> tuple[str, str]:
    key = os.environ.get("REED_API_KEY", "").strip()
    if not key:
        raise RuntimeError("REED_API_KEY is not set in .env")
    return (key, "")


def _clean(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _age_days(posted: str) -> int:
    try:
        return (date.today() - datetime.strptime(posted[:10], "%d/%m/%Y").date()).days
    except ValueError:
        return 0          # undated: let it through rather than lose it


def _location(name: str, searched: str) -> str:
    """Reed often gives a bare postcode ("EC3A8BE"). The search itself was
    limited to a radius around `searched`, so say so - otherwise the location
    filter, which looks for "london", silently drops every postcode-only ad."""
    name = name.strip()
    if searched.lower() in name.lower():
        return name
    return f"{name}, {searched} area" if name else f"{searched} area"


def search(emp: ReedSource, query: str, session: requests.Session | None = None) -> Iterator[Posting]:
    s = session or make_session()
    auth = _auth()
    for page in range(MAX_PAGES):
        resp = s.get(f"{API}/search", auth=auth, timeout=30, params={
            "keywords": query, "locationName": emp.location,
            "distanceFromLocation": emp.distance,
            "resultsToTake": PAGE, "resultsToSkip": page * PAGE})
        resp.raise_for_status()
        results = resp.json().get("results") or []
        for r in results:
            jid = r.get("jobId")
            if not jid:
                continue
            salary = r.get("maximumSalary") or r.get("minimumSalary")
            # Only an annual figure is compared: contract ads quote a DAILY or
            # hourly rate ("450"), which is not a £450 salary.
            if salary and salary >= 1000 and emp.min_salary and salary < emp.min_salary:
                continue
            if _age_days(r.get("date") or "") > emp.max_age_days:
                continue
            yield Posting(
                source=SOURCE,
                employer=(r.get("employerName") or "Unknown advertiser").strip(),
                external_id=f"job:{jid}",
                title=(r.get("jobTitle") or "").strip(),
                location=_location(r.get("locationName") or "", emp.location),
                url=r.get("jobUrl") or f"https://www.reed.co.uk/jobs/{jid}",
                posted_text=(r.get("date") or "")[:10],
                description="",   # full text fetched at scoring time
                extra={"snippet": _clean(r.get("jobDescription") or "")[:600],
                       "salary": salary},
            )
        if len(results) < PAGE:
            return


def fetch_description(emp: ReedSource, posting: Posting, session=None) -> str:
    s = session or make_session()
    jid = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(f"{API}/jobs/{jid}", auth=_auth(), timeout=30)
        resp.raise_for_status()
        return _clean(resp.json().get("jobDescription") or "")
    except (requests.RequestException, ValueError):
        return ""


# Reed answers a withdrawn job with 404, and a live one carries its own expiry
# date: both are explicit, so a False here closes the role on the first reading.
DEFINITIVE_GONE = True


def is_alive(emp: ReedSource, posting: Posting, session=None) -> bool:
    s = session or make_session()
    jid = posting.external_id.split(":", 1)[1]
    try:
        resp = s.get(f"{API}/jobs/{jid}", auth=_auth(), timeout=30)
    except requests.RequestException:
        return True
    if resp.status_code in (404, 410):
        return False
    if resp.status_code != 200:
        return True            # auth or rate limit: about us, not the job
    try:
        exp = (resp.json() or {}).get("expirationDate") or ""
    except ValueError:
        return True
    for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(exp[:19], fmt).date() >= date.today()
        except ValueError:
            continue
    return True

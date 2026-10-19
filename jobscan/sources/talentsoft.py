"""Talentsoft (Cegid) career-site adapter.

Talentsoft portals render their vacancy list server-side at:

    GET {base}/offre-de-emploi/liste-offres.aspx?LCID=2057[&Page=n]

LCID 2057 is en-GB; 1036 is fr-FR. Each vacancy is a `ts-offer-card` block
carrying the requisition reference in `data-reference`, which is the same
reference the employer quotes in correspondence - so it matches cleanly
against applications.yaml.

This is HTML parsing rather than an API, so it is more fragile than the
Workday or Eightfold adapters: a site redesign will break it. The adapter
health check exists precisely to make that visible rather than silent.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Iterator

import requests

from ..net import make_session

from ..models import Posting

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 jobscan/0.1"
MAX_PAGES = 8

# Talentsoft stores the active search criteria in the server-side session, so
# sending `keywords` on one request silently filters every later request made
# on the same session. This adapter therefore never sends a keyword and simply
# paginates the full list; USES_QUERY tells collect() to call it once rather
# than once per configured query.
USES_QUERY = False

# Two Talentsoft themes in the wild: a "card" (<div>) and a "list item" (<li>).
# Split on whichever marker the site uses rather than matching a closing tag,
# which differs between them.
# NB the lookahead must not also match ts-offer-card-content /
# ts-offer-list-item__title, which appear INSIDE a card - hence requiring a
# space or quote straight after, not a word boundary.
_SPLIT = re.compile(r'(?=<(?:div|li) class="ts-offer-(?:card|list-item)(?=[ "]))')
_IS_CARD = re.compile(r'<(?:div|li) class="ts-offer-(?:card|list-item)(?=[ "])')
_HREF = re.compile(r'href="([^"]*/job/[^"]+\.aspx)"')
_TITLE = re.compile(r'data-title="([^"]*)"')
_REF = re.compile(r'data-reference="([^"]*)"')
_LIS = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
_DESC_UL = re.compile(r'<ul class="ts-offer-(?:card-content__list|list-item__description)[^"]*"[^>]*>(.*?)</ul>', re.S)


@dataclass
class TalentsoftEmployer:
    name: str
    base: str          # e.g. https://jobs.amundi.com
    lcid: int = 2057   # 2057 = en-GB


def _txt(s: str) -> str:
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))).strip()


def search(
    emp: TalentsoftEmployer, query: str = "", session: requests.Session | None = None
) -> Iterator[Posting]:
    s = session or make_session()
    seen: set[str] = set()

    for page in range(1, MAX_PAGES + 1):
        params = {"LCID": emp.lcid}
        if page > 1:
            params["Page"] = page
        resp = s.get(
            f"{emp.base.rstrip('/')}/offre-de-emploi/liste-offres.aspx",
            params=params,
            headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"},
            timeout=45,
        )
        resp.raise_for_status()

        cards = [c for c in _SPLIT.split(resp.text) if _IS_CARD.match(c)]
        if not cards:
            return

        new = 0
        for card in cards:
            href = _HREF.search(card)
            if not href:
                continue
            ref = _REF.search(card)
            title = _TITLE.search(card)
            # The description list is [contract type, (entity,) country, city] -
            # the entity is present on some themes and not others, so take the
            # last two entries, which are always country and city.
            ul = _DESC_UL.search(card)
            bits = [b for b in (_txt(x) for x in _LIS.findall(ul.group(1) if ul else "")) if b]
            location = ", ".join(bits[-2:])

            req_id = (ref.group(1) if ref else href.group(1).rsplit("_", 1)[-1].split(".")[0])
            if req_id in seen:
                continue
            seen.add(req_id)
            new += 1

            yield Posting(
                source="talentsoft",
                employer=emp.name,
                external_id=f"{emp.base.split('//')[-1].split('.')[1]}:{req_id}",
                title=_txt(title.group(1)) if title else _txt(card[:200]),
                location=location,
                url=f"{emp.base.rstrip('/')}{href.group(1)}",
                detail_path=href.group(1),
            )

        if new == 0:          # pagination looped back to the same page
            return
        time.sleep(0.4)


def fetch_description(
    emp: TalentsoftEmployer, posting: Posting, session: requests.Session | None = None
) -> str:
    s = session or make_session()
    resp = s.get(posting.url, headers={"User-Agent": UA}, timeout=45)
    resp.raise_for_status()
    html = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", resp.text)
    m = re.search(r'(?s)<div[^>]*class="[^"]*ts-offer-page__description[^"]*"[^>]*>(.*?)</div>\s*</div>', html)
    body = m.group(1) if m else html
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</(p|li|div|h\d)>", "\n", body)
    text = unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:20000]


def is_alive(
    emp: TalentsoftEmployer, posting: Posting, session: requests.Session | None = None
) -> bool:
    s = session or make_session()
    try:
        resp = s.get(posting.url, headers={"User-Agent": UA}, timeout=45)
    except requests.RequestException:
        return True
    if resp.status_code in (404, 410):
        return False
    return resp.status_code < 500

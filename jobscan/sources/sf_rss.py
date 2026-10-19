"""SAP SuccessFactors career-site adapter.

SuccessFactors "career site builder" portals expose a paginated search at:

    GET {base}/search/?q=credit&locationsearch=London&startrow=0

This started out reading the site's RSS feed (/services/rss/job/), which is
cleaner in principle. It was replaced because the feed caps at 20 items with
no offset, and that cap was actively hiding roles that sat on page one of
the search. The search page paginates properly and
carries location in its own column, so coverage is far better.

Not every SuccessFactors theme server-renders that page: Standard Chartered's
builds its results in JavaScript, so the HTML search returns nothing there.
When that happens this adapter falls back to the site's RSS feed, which is
narrower (20 items, no offset) but works. Coverage per employer is therefore
"search page if available, feed otherwise".

It is HTML parsing, so a site redesign will break it - which the adapter
health check is there to surface.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from typing import Iterator

import requests

from ..net import make_session

from ..models import Posting

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 jobscan/0.1"
PAGE = 20
MAX_PAGES = 8
# ".../job/{City}-{Title}/{id}/..." - the numeric run is the requisition id
_ID_RE = re.compile(r"/job/[^/]*/(\d+)/?")
_ROW = re.compile(r'<tr class="data-row">.*?</tr>', re.S)
_LINK = re.compile(r'<a href="([^"]+)"[^>]*class="jobTitle-link"[^>]*>(.*?)</a>', re.S)
_LOC = re.compile(r'<td class="colLocation[^"]*"[^>]*>\s*<span class="jobLocation">\s*(.*?)\s*</span>', re.S)
_DATE = re.compile(r'<span class="jobDate">\s*(.*?)\s*</span>', re.S)
_TOTAL = re.compile(r"Results\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)")


@dataclass
class SFEmployer:
    name: str
    base: str            # e.g. https://jobs.standardchartered.com
    locale: str = "en_GB"

    @property
    def search_url(self) -> str:
        return f"{self.base.rstrip('/')}/search/"

    @property
    def feed_url(self) -> str:
        return f"{self.base.rstrip('/')}/services/rss/job/"


def _search_html(
    emp: SFEmployer, query: str, session: requests.Session | None = None
) -> Iterator[Posting]:
    s = session or make_session()
    start = 0

    for _ in range(MAX_PAGES):
        resp = s.get(
            emp.search_url,
            params={"q": query or "", "startrow": start},
            headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"},
            timeout=45,
        )
        resp.raise_for_status()
        html = resp.text

        rows = _ROW.findall(html)
        if not rows:
            return

        for row in rows:
            link = _LINK.search(row)
            if not link:
                continue
            href, title = link.group(1), _text(link.group(2))
            loc = _LOC.search(row)
            date = _DATE.search(row)
            m = _ID_RE.search(href)
            req_id = m.group(1) if m else href.rstrip("/").rsplit("/", 1)[-1][:40]
            url = href if href.startswith("http") else f"{emp.base.rstrip('/')}{href}"

            yield Posting(
                source="successfactors",
                employer=emp.name,
                external_id=f"{emp.name.lower().replace(' ', '')}:{req_id}",
                title=title,
                location=_text(loc.group(1)) if loc else "",
                url=url,
                detail_path=url,
                posted_text=_text(date.group(1)) if date else "",
            )

        total = _TOTAL.search(html)
        start += PAGE
        if total and start >= int(total.group(1).replace(",", "")):
            return
        time.sleep(0.4)


_TITLE_LOC = re.compile(r"\(([^()]{2,60})\)\s*$")


def _search_rss(
    emp: SFEmployer, query: str, session: requests.Session | None = None
) -> Iterator[Posting]:
    """Fallback for themes whose search page is client-rendered."""
    s = session or make_session()
    resp = s.get(
        emp.feed_url,
        params={"locale": emp.locale, "keywords": f"({query})" if query else ""},
        headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml"},
        timeout=45,
    )
    resp.raise_for_status()
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        location = ""
        m = _TITLE_LOC.search(title)
        if m:
            location = m.group(1).strip()
            title = title[: m.start()].strip()
        m = _ID_RE.search(link)
        req_id = m.group(1) if m else link.rsplit("/", 1)[-1][:40]
        yield Posting(
            source="successfactors",
            employer=emp.name,
            external_id=f"{emp.name.lower().replace(' ', '')}:{req_id}",
            title=title, location=location, url=link, detail_path=link,
            posted_text=(item.findtext("pubDate") or "").strip(),
        )


def search(
    emp: SFEmployer, query: str, session: requests.Session | None = None
) -> Iterator[Posting]:
    """Search page where it renders server-side, RSS feed where it does not."""
    got = False
    for posting in _search_html(emp, query, session):
        got = True
        yield posting
    if not got:
        yield from _search_rss(emp, query, session)


def _text(raw: str) -> str:
    """Row cells contain markup and entities; flatten to plain text."""
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw or ""))).strip()


def _strip(html: str) -> str:
    text = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|li|div|h\d|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
        .replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    )
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch_description(
    emp: SFEmployer, posting: Posting, session: requests.Session | None = None
) -> str:
    s = session or make_session()
    resp = s.get(posting.detail_path or posting.url,
                 headers={"User-Agent": UA}, timeout=45)
    resp.raise_for_status()
    html = resp.text
    # The CSB job page wraps the advert in this block; fall back to the page.
    m = re.search(r'(?s)<div[^>]*class="[^"]*jobDescription[^"]*"[^>]*>(.*?)</div>\s*</div>', html)
    return _strip(m.group(1) if m else html)[:20000]


def is_alive(
    emp: SFEmployer, posting: Posting, session: requests.Session | None = None
) -> bool:
    s = session or make_session()
    try:
        resp = s.get(posting.detail_path or posting.url,
                     headers={"User-Agent": UA}, timeout=45, allow_redirects=True)
    except requests.RequestException:
        return True
    if resp.status_code in (404, 410):
        return False
    return resp.status_code < 500

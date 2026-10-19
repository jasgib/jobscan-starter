"""Stage 1: free local filtering.

Everything here is string matching. Its only job is to cut the volume that
reaches the paid scoring stage, so it errs towards letting things through.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .models import Posting


@lru_cache(maxsize=256)
def _word_re(term: str) -> re.Pattern:
    """Whole-word matcher. Without this, 'intern' silently kills every
    'Internal Audit' role and 'quant' kills nothing useful either way."""
    return re.compile(rf"(?<!\w){re.escape(term.strip().lower())}(?!\w)")


# A location that names only the country. Oracle Cloud and several other
# platforms list a role as just "United Kingdom" and carry no city anywhere -
# not in the field, the title or the URL - so a London role there could never
# pass. These go to the scorer, which reads the description; some will turn out
# to be Swindon or Leeds, and the verdict is where that gets said.
_COUNTRY_ONLY = re.compile(
    r"^\s*(united kingdom( of great britain( and northern ireland)?)?|uk|gb|gbr|"
    r"great britain|england)\s*$", re.I)


def matches_location(posting: Posting, terms: list[str]) -> bool:
    if not terms:
        return True
    if _COUNTRY_ONLY.match(posting.location or ""):
        return True
    # The URL and detail path are part of the haystack because a multi-site
    # Workday requisition reports its location as the literal string
    # "2 Locations" - the city names appear nowhere in the field. Matching on
    # location alone silently dropped 81 London postings, among them an FCA
    # supervision associate seat and several Lloyds credit roles, none of
    # which ever reached the scorer to be judged.
    hay = " ".join((posting.location, posting.title,
                    posting.url or "", posting.detail_path or "")).lower()
    return any(t.lower() in hay for t in terms)


def title_excluded(posting: Posting, terms: list[str]) -> bool:
    """Exclusions match whole words only, so they must be listed in full:
    'intern' and 'internship' are separate entries."""
    title = posting.title.lower()
    return any(_word_re(t).search(title) for t in terms)


def seniority_excluded(
    posting: Posting, senior_terms: list[str], level_terms: list[str]
) -> bool:
    """Drop roles that are above your level, unless the title also carries a
    level marker. 'Chief Underwriting Office, Associate' is an associate seat
    on a team whose head is a Chief, and must survive."""
    title = posting.title.lower()
    if any(_word_re(t).search(title) for t in level_terms):
        return False
    return any(_word_re(t).search(title) for t in senior_terms)


def matches_keywords(posting: Posting, terms: list[str]) -> bool:
    if not terms:
        return True
    hay = f"{posting.title} {posting.description}".lower()
    return any(t.lower() in hay for t in terms)


def prefilter(posting: Posting, cfg: dict) -> tuple[bool, str]:
    """Return (keep, reason_if_dropped)."""
    search = cfg.get("search", {})

    if not matches_location(posting, search.get("location_terms", [])):
        return False, "location"
    if title_excluded(posting, search.get("exclude_title_terms", [])):
        return False, "excluded title term"
    if seniority_excluded(
        posting,
        search.get("seniority_exclude_terms", []),
        search.get("level_terms", []),
    ):
        return False, "above target level"
    # The include-keyword rule is off by default: before the description is
    # fetched it can only see the title, and rejecting on title words drops
    # good roles silently. Everything that survives the cheap rules above is
    # judged on the full description instead. Set search.require_keyword to
    # true to turn it on.
    if not search.get("require_keyword", False):
        return True, ""

    if posting.employer in (cfg.get("_score_all_employers") or set()):
        return True, ""

    if not matches_keywords(posting, search.get("include_terms", [])):
        return False, "no keyword match"
    return True, ""

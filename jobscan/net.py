"""Shared HTTP session with retries.

Every adapter takes a requests.Session, so giving that session a retry policy
fixes transient failures everywhere at once rather than per adapter.

The failures being handled are real: when a laptop wakes from sleep the
network is not immediately up, and whichever employer is scanned first eats a
DNS failure or a read timeout and would otherwise be recorded as failed for
the whole run.

POST is included in the retry set deliberately. It is normally excluded
because retrying a POST can duplicate a side effect - but these POSTs are
search queries, which are read-only, so replaying one is harmless.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 45


def make_session(total: int = 3, backoff: float = 1.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=total,
        connect=total,
        read=total,
        status=total,
        backoff_factor=backoff,          # 0s, 1.5s, 3s, 6s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

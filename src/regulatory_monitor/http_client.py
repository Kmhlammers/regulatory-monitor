"""Shared HTTP session for all fetchers."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "nl,en;q=0.8",
}

# Some sources (notably repository.overheid.nl's SRU endpoint) rate-limit with a
# 429 and a Retry-After header when hit fast — a real risk once this runs
# unattended from CI rather than interactively. Retry transient failures with
# exponential backoff and honour Retry-After so one throttled source doesn't turn
# into a spurious "API fout" in the published report.
_RETRY = Retry(
    total=4,
    backoff_factor=1.0,  # 0s, 1s, 2s, 4s between attempts
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "POST"),
    respect_retry_after_header=True,
    raise_on_status=False,
)


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HTTP_HEADERS)
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

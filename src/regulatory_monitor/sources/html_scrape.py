"""HTML-scraping sources without a usable RSS/sitemap/API: ACM, FOD Volksgezondheid,
CEN/CENELEC, SCCS. These are the most fragile fetchers (no structured feed to fall
back on) — any layout change on the target site can break the CSS selectors below,
so failures here should always surface as a manual-check note rather than crash
the whole run.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..http_client import new_session
from ..models import Publication, SourceCount


def _make_count(label: str, from_date: date, to_date: date, relevant: int, total: int, api_error: bool, note: str) -> SourceCount:
    return SourceCount(
        label=label,
        date_str=f"{from_date.isoformat()} t/m {to_date.isoformat()}" if from_date != to_date else from_date.isoformat(),
        relevant=relevant, total=total, api_error=api_error, note=note,
    )


def fetch_acm(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """ACM nieuws: HTML-scraping, datum uit div.m-card__meta (RSS is leeg)."""
    label = "Nieuws | ACM"
    base_url = "https://www.acm.nl"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""
    date_re = re.compile(r"(\d{2})-(\d{2})-(\d{4})$")

    try:
        session = new_session()
        resp = session.get(f"{base_url}/nl/nieuws", timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for card in soup.select(".m-card"):
            meta_el = card.select_one(".m-card__meta")
            meta_text = meta_el.get_text(strip=True) if meta_el else ""
            m = date_re.search(meta_text)
            if not m:
                continue
            item_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if not (from_date <= item_date <= to_date):
                continue
            title_el = card.select_one(".m-card__title, h2, h3")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            link_el = card.select_one("a[href]")
            link = urljoin(base_url, link_el["href"]) if link_el else base_url
            total += 1
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=link, pub_date=item_date))
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    return pubs, _make_count(label, from_date, to_date, len(pubs), total, api_error, error_note)


_FOD_TITLE_PREFIX_RE = re.compile(r"^Ga naar:\s*", re.IGNORECASE)


def fetch_fod_vg(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """FOD Volksgezondheid nieuws: HTML-scraping via section.search-result__wrapper.

    Elke sectie bevat één <time datetime=...> en één <a title="Ga naar: ...">
    met de volledige, schone titel (de zichtbare linktekst zelf bevat
    aaneengeplakte breadcrumb-labels zonder spaties, dus die wordt niet gebruikt).
    """
    label = "Nieuws | FOD Volksgezondheid"
    base_url = "https://www.health.belgium.be"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    try:
        session = new_session()
        resp = session.get(f"{base_url}/nl/nieuws", timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for section in soup.select("section.search-result__wrapper"):
            time_tag = section.find("time")
            if not time_tag or not time_tag.get("datetime"):
                continue
            try:
                item_date = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00")).date()
            except ValueError:
                continue
            if not (from_date <= item_date <= to_date):
                continue
            link_el = section.find("a", href=True, title=True)
            if not link_el:
                continue
            title = _FOD_TITLE_PREFIX_RE.sub("", link_el["title"]).strip()
            if not title:
                continue
            link = urljoin(base_url, link_el["href"])
            total += 1
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=link, pub_date=item_date))
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    return pubs, _make_count(label, from_date, to_date, len(pubs), total, api_error, error_note)


def fetch_cen_cenelec(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """CEN/CENELEC nieuws (experimenteel). Geen datumfilter beschikbaar op de listingpagina;
    telt daarom alle huidige items op de pagina mee (total), niet alleen de opgevraagde periode."""
    label = "CEN/CENELEC normen"
    base_url = "https://www.cen.eu"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    try:
        session = new_session()
        resp = session.get(f"{base_url}/news/Pages/default.aspx", timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        seen = set()
        for link_el in soup.select("a[href*='/news/']"):
            title = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            if not title or href in seen:
                continue
            seen.add(href)
            total += 1
            link = urljoin(base_url, href)
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=link, pub_date=None))
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    return pubs, _make_count(label, from_date, to_date, len(pubs), total, api_error, error_note)


def fetch_sccs(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """SCCS (cosmetica, experimenteel). Geen datumfilter beschikbaar op de listingpagina."""
    label = "SCCS (cosmetica)"
    base_url = "https://health.ec.europa.eu"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    try:
        session = new_session()
        resp = session.get(
            f"{base_url}/scientific-committees/scientific-committee-consumer-safety-sccs_en", timeout=20,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        seen = set()
        for link_el in soup.select("a[href*='opinion'], a[href*='publication']"):
            title = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            if not title or href in seen:
                continue
            seen.add(href)
            total += 1
            link = urljoin(base_url, href)
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=link, pub_date=None))
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    return pubs, _make_count(label, from_date, to_date, len(pubs), total, api_error, error_note)


def fetch_fod_economie(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """FOD Economie BE (experimenteel) via RSS."""
    from .rss import _rss_weekly
    return _rss_weekly("FOD Economie BE", "https://economie.fgov.be/nl/rss/nieuws", from_date, to_date, matcher)

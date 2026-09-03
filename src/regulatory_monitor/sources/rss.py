"""RSS-based sources: ECHA, Internal Market, Environment, FAVV, RVO, EUON, EFSA, EC News."""
from __future__ import annotations

from datetime import date, datetime

import feedparser
import requests

from ..http_client import new_session
from ..models import Publication, SourceCount


def _parse_entry_date(entry) -> date | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return date(*entry.published_parsed[:3])
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return date(*entry.updated_parsed[:3])
    return None


def _rss_weekly(
    label: str,
    feed_url: str,
    from_date: date,
    to_date: date,
    matcher,
    always_relevant: bool = False,
    default_topic: str = "",
    exclude_types: list[str] | None = None,
) -> tuple[list[Publication], SourceCount]:
    """Generieke RSS-fetcher voor wekelijkse bronnen.

    exclude_types: lijst van woorden in de titel die items uitsluiten (bijv.
    ['Recall', 'Agenda']).
    always_relevant: sla keyword-matching over en gebruik altijd default_topic
    (voor bronnen waarvan iedere publicatie relevant is, zoals ECHA News).
    """
    exclude_types = exclude_types or []
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    try:
        session = new_session()
        resp = session.get(feed_url, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS-feed kon niet geparsed worden: {feed.bozo_exception}")

        for entry in feed.entries:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            if any(t.lower() in title.lower() for t in exclude_types):
                continue
            entry_date = _parse_entry_date(entry)
            if entry_date and not (from_date <= entry_date <= to_date):
                continue
            total += 1
            link = getattr(entry, "link", "")
            if always_relevant:
                pubs.append(Publication(source=label, topic=default_topic, title=title, url=link, pub_date=entry_date))
                continue
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=link, pub_date=entry_date))
    except (requests.RequestException, ValueError) as exc:
        api_error = True
        error_note = str(exc)

    count = SourceCount(
        label=label,
        date_str=f"{from_date.isoformat()} t/m {to_date.isoformat()}" if from_date != to_date else from_date.isoformat(),
        relevant=len(pubs), total=total, api_error=api_error, note=error_note,
    )
    return pubs, count


def fetch_echa_news(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """ECHA News: altijd relevant (default topic: REACH)."""
    return _rss_weekly(
        "News - ECHA", "https://echa.europa.eu/nl/rss/news", from_date, to_date, matcher,
        always_relevant=True, default_topic="REACH",
    )


def fetch_single_market(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly("News - Internal Market", "https://single-market-economy.ec.europa.eu/node/2/rss_en", from_date, to_date, matcher)


def fetch_env_publications(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly("Publications - Environment", "https://environment.ec.europa.eu/node/92/rss_en", from_date, to_date, matcher)


def fetch_favv_publications(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly(
        "Publicaties | Federaal Agentschap voor de veiligheid van de voedselketen",
        "https://favv-afsca.be/nl/publications?output=rss", from_date, to_date, matcher,
    )


def fetch_favv_news(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly(
        "Nieuws | Federaal Agentschap voor de veiligheid van de voedselketen",
        "https://favv-afsca.be/nl/news?output=rss", from_date, to_date, matcher,
    )


def fetch_rvo(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly("RVO (MVO/NL)", "https://www.rvo.nl/rss/nieuws", from_date, to_date, matcher)


def fetch_euon(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly("EUON (nanomaterialen)", "https://euon.echa.europa.eu/rss/news", from_date, to_date, matcher)


def fetch_efsa(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _rss_weekly("EFSA (FCM)", "https://www.efsa.europa.eu/en/rss/news", from_date, to_date, matcher)


_EC_RSS_URL = "https://ec.europa.eu/commission/presscorner/api/rss?lang=en"


def fetch_ec_news_daily(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """EC News. In het origineel is de presscorner zoek-API-call er nog wel,
    maar expliciet uitgeschakeld door de auteur zelf (``if False else None``,
    met commentaar "presscorner API niet beschikbaar") — live testen bevestigt
    dat: de API geeft nu HTTP 404. Dit gaat dus altijd via de RSS-feed, die
    zoals de originele docstring al toegaf maar ~10 items heeft en veel
    publicaties mist. Dat is een bekende, geaccepteerde beperking van de
    huidige tool, geen nieuw defect.
    """
    label = "EC Nieuws"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    try:
        feed = feedparser.parse(_EC_RSS_URL)
        for entry in feed.entries:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            entry_date = _parse_entry_date(entry)
            if entry_date and not (from_date <= entry_date <= to_date):
                continue
            total += 1
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=getattr(entry, "link", ""), pub_date=entry_date))
    except Exception as exc:  # noqa: BLE001
        api_error = True
        error_note = str(exc)

    count = SourceCount(
        label=label,
        date_str=f"{from_date.isoformat()} t/m {to_date.isoformat()}" if from_date != to_date else from_date.isoformat(),
        relevant=len(pubs), total=total, api_error=api_error, note=error_note,
    )
    return pubs, count

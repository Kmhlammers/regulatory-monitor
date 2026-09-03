"""Generic sitemap.xml fetcher used for NVWA, Arbeidsinspectie en ROW.

Haalt publicaties op via base_url/sitemap/N.xml. Filtert op URL-pad dat
path_filter bevat, en (normaal) op datum YYYY/MM/DD in de URL. Stopt zodra
alle lastmod-waarden in een sitemap ouder zijn dan from_date, zodat niet alle
sitemappagina's van een site doorlopen hoeven te worden.

Sitemaps bevatten geen titel, alleen <loc> en <lastmod>; de titel wordt bij
gebrek daaraan afgeleid uit het laatste pad-segment van de URL.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from xml.etree import ElementTree as ET

from ..http_client import new_session
from ..models import Publication, SourceCount

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


def _title_from_url(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = slug.rsplit(".", 1)[0]
    return slug.replace("-", " ").replace("_", " ").strip().capitalize()


def _extract_date(url: str, lastmod: str | None, use_lastmod_as_date: bool) -> date | None:
    if use_lastmod_as_date and lastmod:
        try:
            return datetime.fromisoformat(lastmod.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    m = _URL_DATE_RE.search(url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if lastmod:
        try:
            return datetime.fromisoformat(lastmod.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def fetch_sitemap_dated_urls(
    label: str,
    base_url: str,
    path_filter: str,
    from_date: date,
    to_date: date,
    matcher,
    max_sitemaps: int = 20,
    exclude_title_words: list[str] | None = None,
    use_lastmod_as_date: bool = False,
) -> tuple[list[Publication], SourceCount]:
    session = new_session()
    exclude_title_words = exclude_title_words or []
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    try:
        for n in range(1, max_sitemaps + 1):
            url = f"{base_url}/sitemap/{n}.xml"
            resp = session.get(url, timeout=20)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

            entries = []
            for entry in root.findall("sm:url", _SITEMAP_NS):
                loc = entry.findtext("sm:loc", default="", namespaces=_SITEMAP_NS)
                lastmod = entry.findtext("sm:lastmod", default="", namespaces=_SITEMAP_NS)
                entries.append((loc, lastmod))

            all_too_old = True
            for loc, lastmod in entries:
                if path_filter not in loc:
                    continue
                pub_date = _extract_date(loc, lastmod, use_lastmod_as_date)
                if pub_date is None:
                    continue
                if pub_date > to_date:
                    continue
                if pub_date < from_date:
                    continue
                all_too_old = False
                total += 1
                title = _title_from_url(loc)
                if any(word.lower() in title.lower() for word in exclude_title_words):
                    continue
                result = matcher.match(title)
                if result.relevant:
                    pubs.append(Publication(source=label, topic=result.topic, title=title, url=loc, pub_date=pub_date))

            if entries and all_too_old:
                break
    except Exception as exc:  # noqa: BLE001 - surface any fetch/parse failure as a source-level error
        api_error = True
        error_note = str(exc)

    count = SourceCount(
        label=label,
        date_str=f"{from_date.isoformat()} t/m {to_date.isoformat()}" if from_date != to_date else from_date.isoformat(),
        relevant=len(pubs), total=total, api_error=api_error, note=error_note,
    )
    return pubs, count


_NVWA_NEWS_EXCLUDE_WORDS = [
    "terugroeping", "veiligheidswaarschuwing", "waarschuw", "inspecteur-generaal",
    "directeur-generaal", "raad-van-bestuur", "benoeming", "aanstelling", "afscheid",
    "bestuurder", "telers-", "gewasbescherming", "akkerbouw", "tuinbouw", "sierteelt",
    "veehouderij", "veeteelt",
]


def fetch_nvwa_news(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return fetch_sitemap_dated_urls(
        "Nieuws en media | NVWA", "https://www.nvwa.nl", "/actueel/nieuws/",
        from_date, to_date, matcher, exclude_title_words=_NVWA_NEWS_EXCLUDE_WORDS,
    )


def fetch_nvwa_docs(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """FIX 2026-08-17: the original tool required a YYYY/MM/DD date in the URL
    path to accept a sitemap entry, which is why its own MANUAL_CHECK_NOTES
    calls this a "subset". Checked live: only ~3% of /documenten/ URLs on
    nvwa.nl actually have that pattern (4 of 125 sampled) — so in practice the
    original captured almost nothing here, not just "a subset". This fetcher
    (via _extract_date's unconditional lastmod fallback, same idea as ROW)
    picks up the other ~97% using the sitemap's <lastmod> instead. Caveat:
    unlike ROW, there's no confirmation from NVWA that lastmod always tracks
    genuine publish date rather than any content touch — worth spot-checking
    against nvwa.nl before fully trusting the count.
    """
    return fetch_sitemap_dated_urls("Documenten | NVWA", "https://www.nvwa.nl", "/documenten/", from_date, to_date, matcher)


def fetch_arbeidsinspectie_news(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return fetch_sitemap_dated_urls(
        "Nieuws | Nederlandse Arbeidsinspectie", "https://www.nlarbeidsinspectie.nl",
        "/actueel/nieuws/", from_date, to_date, matcher,
    )


def fetch_arbeidsinspectie_docs(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return fetch_sitemap_dated_urls(
        "Publicaties | Nederlandse Arbeidsinspectie", "https://www.nlarbeidsinspectie.nl",
        "/documenten/", from_date, to_date, matcher,
    )


def fetch_row(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """ROW: sitemap-gebaseerd op lastmod (= publicatiedatum op de website).

    De datum in de URL is de vergaderdatum; lastmod is wanneer het document
    online kwam.
    """
    return fetch_sitemap_dated_urls(
        "ROW", "https://www.row-minvws.nl", "/documenten/", from_date, to_date, matcher,
        use_lastmod_as_date=True,
    )

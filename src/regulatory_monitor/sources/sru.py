"""officielebekendmakingen.nl SRU-API: Staatsblad, Staatscourant, Parlementaire documenten.

FIXED 2026-08-17. The original tool queried
``https://zoek.officielebekendmakingen.nl/sru/Search`` — that endpoint is dead
(HTTP 500 for the simple date+identifier query, a clean-but-fatal
"Invalid search field : c.product-area" diagnostic for the product-area
query). Research into KOOP's own documentation (Handleiding SRU 2.0 v1.4,
published 2026-06-02 — after the original tool was built in May) turned up
the real successor endpoint: ``https://repository.overheid.nl/sru``. Verified
live: it accepts the same CQL (``c.product-area==officielepublicaties`` etc.)
and returns real records — e.g. 4 Staatsblad publications for 2026-08-14,
146 Staatscourant, 21 Kamerstukken. This is a confirmed fix, not a guess:
KOOP migrated the endpoint; the CQL query language and field names carried
over unchanged.

One field did NOT carry over: ``identifier any "<prefix>"`` now returns
"Unsupported index". So instead of asking the server to filter by
document-type prefix, this fetches by ``w.publicatienaam`` (e.g. "Staatsblad",
"Staatscourant") — which the original script already used for the
Parlementair query — and, for Staatscourant, filters client-side on
``organisatietype`` (present directly in the response, no extra request
needed).
"""
from __future__ import annotations

import time
import urllib.parse
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from ..http_client import new_session
from ..models import Publication, SourceCount

_SRU_URL = "https://repository.overheid.nl/sru"

_NS = {
    "sru": "http://docs.oasis-open.org/ns/search-ws/sruResponse",
    "diag": "http://docs.oasis-open.org/ns/search-ws/diagnostic",
    "gzd": "http://standaarden.overheid.nl/sru",
    "ow": "http://standaarden.overheid.nl/wetgeving/",
    "dcterms": "http://purl.org/dc/terms/",
}

_PARL_PUBLICATIENAMEN = [
    "Agenda", "Handelingen", "Kamerstuk",
    "Kamervragen (Aanhangsel)", "Kamervragen zonder antwoord", "Niet-dossierstuk",
]


def _date_range(from_date: date, to_date: date):
    d = from_date
    while d <= to_date:
        yield d
        d += timedelta(days=1)


def _date_str_display(from_date: date, to_date: date) -> str:
    if from_date == to_date:
        return from_date.strftime("%d-%m-%Y")
    return f"{from_date.strftime('%d-%m-%Y')} t/m {to_date.strftime('%d-%m-%Y')}"


def _query(target: date, publicatienaam: str) -> str:
    # publicatienaam is double-quoted: unquoted values containing spaces or
    # parentheses (e.g. "Kamervragen (Aanhangsel)") are misparsed as CQL
    # structure — confirmed live via a "mismatched input '('" diagnostic.
    return f'(c.product-area==officielepublicaties)and(dt.available=={target.isoformat()})and(w.publicatienaam=="{publicatienaam}")'


def _run_query(session, query: str, start_record: int = 1, max_records: int = 100) -> ET.Element:
    """Runs one searchRetrieve request. Raises ValueError on any recognised failure mode."""
    params = urllib.parse.urlencode({
        "version": "1.2",
        "operation": "searchRetrieve",
        "query": query,
        "maximumRecords": max_records,
        "startRecord": start_record,
    })
    resp = session.get(f"{_SRU_URL}?{params}", timeout=30)
    resp.raise_for_status()
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise ValueError(f"SRU XML kon niet geparsed worden: {exc}") from exc

    diagnostic = root.find(".//diag:diagnostic", _NS)
    if diagnostic is not None:
        msg = diagnostic.findtext("diag:message", default="", namespaces=_NS)
        detail = diagnostic.findtext("diag:details", default="", namespaces=_NS)
        raise ValueError(f"SRU diagnostic: {msg} ({detail})")
    return root


def _extract_records(root: ET.Element) -> list[tuple[str, str, str, str]]:
    """Returns (identifier, title, url, organisatietype) tuples."""
    out = []
    for rec in root.findall(".//gzd:gzd", _NS):
        kern = rec.find(".//ow:owmskern", _NS)
        mantel = rec.find(".//ow:owmsmantel", _NS)
        if kern is None:
            continue
        identifier = kern.findtext("dcterms:identifier", default="", namespaces=_NS)
        title = kern.findtext("dcterms:title", default="", namespaces=_NS)
        url = ""
        if mantel is not None:
            hv = mantel.find("dcterms:hasVersion", _NS)
            if hv is not None:
                url = hv.get("resourceIdentifier", "")
        org_type = rec.findtext(".//ow:organisatietype", default="", namespaces=_NS)
        if title:
            out.append((identifier, title, url or f"https://zoek.officielebekendmakingen.nl/{identifier}.html", org_type))
    return out


def _number_of_records(root: ET.Element) -> int:
    text = root.findtext("sru:numberOfRecords", default="0", namespaces=_NS)
    try:
        return int(text)
    except ValueError:
        return 0


def _fetch_by_publicatienaam(
    session, target: date, publicatienaam: str, org_type_filter: str | None,
) -> tuple[list[tuple[str, str, str, str]], int, bool]:
    """Fetches every record for one day + publicatienaam, paginating as needed.

    Returns (records, total_seen, had_api_error). Records are already filtered
    by org_type_filter (substring match on organisatietype) if given.
    """
    records: list[tuple[str, str, str, str]] = []
    total_seen = 0
    start = 1
    page_size = 100
    query = _query(target, publicatienaam)
    try:
        while True:
            root = _run_query(session, query, start_record=start, max_records=page_size)
            page_records = _extract_records(root)
            n = _number_of_records(root)
            for identifier, title, url, org_type in page_records:
                if org_type_filter:
                    if org_type_filter.lower() not in org_type.lower():
                        continue
                total_seen += 1
                records.append((identifier, title, url, org_type))
            if not page_records or start + len(page_records) - 1 >= n:
                break
            start += len(page_records)
            time.sleep(0.15)
    except ValueError:
        return records, total_seen, True
    return records, total_seen, False


def fetch_staatsblad(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _fetch_ob(from_date, to_date, matcher, "Staatsblad NL", "Staatsblad")


def fetch_staatscourant_ministerie(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    return _fetch_ob(from_date, to_date, matcher, "Staatscourant – Ministerie", "Staatscourant", org_type_filter="ministerie")


def fetch_staatscourant_dienst(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """Dienst en agentschap – inclusief NVWA en overig."""
    return _fetch_ob(from_date, to_date, matcher, "Staatscourant – Dienst/agentschap", "Staatscourant", org_type_filter="dienst")


def _fetch_ob(
    from_date: date, to_date: date, matcher, label: str, publicatienaam: str, org_type_filter: str | None = None,
) -> tuple[list[Publication], SourceCount]:
    session = new_session()
    pubs: list[Publication] = []
    total = 0
    api_error = False

    for target in _date_range(from_date, to_date):
        records, total_seen, day_error = _fetch_by_publicatienaam(session, target, publicatienaam, org_type_filter)
        total += total_seen
        api_error = api_error or day_error
        for identifier, title, url, _org_type in records:
            result = matcher.match(title)
            if result.relevant:
                pubs.append(Publication(source=label, topic=result.topic, title=title, url=url, pub_date=target))
        time.sleep(0.15)

    count = SourceCount(
        label=label, date_str=_date_str_display(from_date, to_date),
        relevant=len(pubs), total=total, api_error=api_error,
        note="SRU-fout tijdens ophalen — mogelijk gedeeltelijke resultaten" if api_error else "",
    )
    return pubs, count


def fetch_parlementair(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """Parlementaire documenten: Agenda, Handelingen, Kamerstuk, Kamervragen, Niet-dossierstuk."""
    session = new_session()
    label = "Parlementaire documenten NL"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    seen: set[str] = set()

    for target in _date_range(from_date, to_date):
        for publicatienaam in _PARL_PUBLICATIENAMEN:
            records, total_seen, day_error = _fetch_by_publicatienaam(session, target, publicatienaam, None)
            total += total_seen
            api_error = api_error or day_error
            for identifier, title, url, _org_type in records:
                if url in seen:
                    continue
                seen.add(url)
                result = matcher.match(title)
                if result.relevant:
                    pubs.append(Publication(source=label, topic=result.topic, title=title, url=url, pub_date=target))
            time.sleep(0.15)

    count = SourceCount(
        label=label, date_str=_date_str_display(from_date, to_date),
        relevant=len(pubs), total=total, api_error=api_error,
        note="SRU-fout tijdens ophalen — mogelijk gedeeltelijke resultaten" if api_error else "",
    )
    return pubs, count

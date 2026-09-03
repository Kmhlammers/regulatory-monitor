"""Orchestrates fetchers across sources, per daily/weekly cadence."""
from __future__ import annotations

from datetime import date
from typing import Callable

from . import sources as s
from .config import MonitorConfig
from .matching import RelevanceMatcher
from .models import Publication, SourceCount

Fetcher = Callable[[date, date, RelevanceMatcher], tuple[list[Publication], SourceCount]]

# Canonical label -> fetcher. Labels match nonfood_monitor_config.json's bron_details
# / manual_check_notes keys wherever the config defines one, so counts and manual-check
# notes line up automatically in the pipeline output.
SOURCE_REGISTRY: dict[str, Fetcher] = {
    "Staatsblad NL": s.fetch_staatsblad,
    "Staatscourant – Ministerie": s.fetch_staatscourant_ministerie,
    "Staatscourant – Dienst/agentschap": s.fetch_staatscourant_dienst,
    "Parlementaire documenten NL": s.fetch_parlementair,
    "refLex Chrono BE": s.fetch_reflex,
    "Belgisch Staatsblad": s.fetch_belgisch_staatsblad,
    "E-justice België (Justel)": s.fetch_justel,
    "EC Nieuws": s.fetch_ec_news_daily,
    "EUR-Lex OJ L": lambda f, t, m: s.fetch_eurlex_oj("EUR-Lex OJ L", "L", f, t, m),
    "EUR-Lex OJ C": lambda f, t, m: s.fetch_eurlex_oj("EUR-Lex OJ C", "C", f, t, m),
    "COM-documenten": s.fetch_com_documents,
    "JOIN-documenten": s.fetch_join_documents,
    "SEC/SWD": s.fetch_swd_documents,
    "ROW": s.fetch_row,
    "Nieuws en media | NVWA": s.fetch_nvwa_news,
    "Documenten | NVWA": s.fetch_nvwa_docs,
    "Nieuws | Nederlandse Arbeidsinspectie": s.fetch_arbeidsinspectie_news,
    "Publicaties | Nederlandse Arbeidsinspectie": s.fetch_arbeidsinspectie_docs,
    "Nieuws | ACM": s.fetch_acm,
    "Publicaties | Federaal Agentschap voor de veiligheid van de voedselketen": s.fetch_favv_publications,
    "Nieuws | Federaal Agentschap voor de veiligheid van de voedselketen": s.fetch_favv_news,
    "Nieuws | FOD Volksgezondheid": s.fetch_fod_vg,
    "News - ECHA": s.fetch_echa_news,
    "CEN/CENELEC normen": s.fetch_cen_cenelec,
    "FOD Economie BE": s.fetch_fod_economie,
    "RVO (MVO/NL)": s.fetch_rvo,
    "SCCS (cosmetica)": s.fetch_sccs,
    "EUON (nanomaterialen)": s.fetch_euon,
    "EFSA (FCM)": s.fetch_efsa,
}

# Daily cadence per config's bronnen.dagelijks, plus "Belgisch Staatsblad" which the
# original code fetches daily alongside refLex Chrono BE (both publish daily) even
# though it isn't listed in the config's own "dagelijks" array.
DAILY_SOURCES = [
    "Staatsblad NL",
    "Staatscourant – Ministerie",
    "Staatscourant – Dienst/agentschap",
    "Parlementaire documenten NL",
    "refLex Chrono BE",
    "Belgisch Staatsblad",
    "EC Nieuws",
    "EUR-Lex OJ L",
    "EUR-Lex OJ C",
]

WEEKLY_SOURCES = [
    "COM-documenten",
    "JOIN-documenten",
    "SEC/SWD",
    "ROW",
    "E-justice België (Justel)",
    "Nieuws en media | NVWA",
    "Documenten | NVWA",
    "Nieuws | Nederlandse Arbeidsinspectie",
    "Publicaties | Nederlandse Arbeidsinspectie",
    "Nieuws | ACM",
    "Publicaties | Federaal Agentschap voor de veiligheid van de voedselketen",
    "Nieuws | Federaal Agentschap voor de veiligheid van de voedselketen",
    "Nieuws | FOD Volksgezondheid",
    "News - ECHA",
]

EXPERIMENTAL_WEEKLY_SOURCES = [
    "CEN/CENELEC normen",
    "FOD Economie BE",
    "RVO (MVO/NL)",
    "SCCS (cosmetica)",
    "EUON (nanomaterialen)",
    "EFSA (FCM)",
]


def run_sources(
    source_labels: list[str],
    from_date: date,
    to_date: date,
    matcher: RelevanceMatcher,
    week: str = "",
    experimental_labels: set[str] | None = None,
) -> tuple[list[Publication], list[SourceCount]]:
    """Fetches every source in source_labels and returns combined (publications, counts).

    experimental_labels: source labels that get an "[EXP] " prefix on their topic,
    so they're visually distinguishable in the results without needing a separate tab.
    """
    experimental_labels = experimental_labels or set()
    all_pubs: list[Publication] = []
    all_counts: list[SourceCount] = []

    for label in source_labels:
        fetcher = SOURCE_REGISTRY.get(label)
        if fetcher is None:
            all_counts.append(SourceCount(label=label, date_str=from_date.isoformat(), api_error=True, note="Onbekende bron (niet in SOURCE_REGISTRY)"))
            continue
        try:
            pubs, count = fetcher(from_date, to_date, matcher)
        except Exception as exc:  # noqa: BLE001 - one broken source must not abort the whole run
            all_counts.append(SourceCount(label=label, date_str=from_date.isoformat(), api_error=True, note=str(exc)))
            continue

        if label in experimental_labels:
            for p in pubs:
                p.topic = f"[EXP] {p.topic}"
        for p in pubs:
            p.week = week
        all_pubs.extend(pubs)
        all_counts.append(count)

    return all_pubs, all_counts


def deduplicate(publications: list[Publication]) -> list[Publication]:
    """Drops duplicate (title, url) pairs, keeping the first occurrence."""
    seen: set[tuple[str, str]] = set()
    unique: list[Publication] = []
    for pub in publications:
        key = (pub.title.strip().lower(), pub.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(pub)
    return unique


def find_antidumping_hits(publications_by_source_titles: list[tuple[str, str, str]], matcher: RelevanceMatcher) -> list[tuple[str, str, str]]:
    """Given (source, title, url) tuples already fetched, returns those matching antidumping_keywords."""
    return [(source, title, url) for source, title, url in publications_by_source_titles if matcher.is_antidumping(title)]

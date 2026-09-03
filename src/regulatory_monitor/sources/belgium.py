"""Belgische bronnen: ejustice (Belgisch Staatsblad), Justel en refLex Chrono BE.

fetch_belgisch_staatsblad / fetch_reflex zijn een directe port van de echte
functies uit regulatory_monitor.py van de collega (bevestigd tegen haar bron).
fetch_justel gebruikt dezelfde truc: de interactieve zoekpagina (rech.pl) vereist
JavaScript, maar de resultatenlijst list.pl geeft — net als summary.pl bij het
Staatsblad en de maandlijst bij refLex — volledig server-side gerenderde HTML terug
met een filter op publicatiedatum (pdd/pdf).
"""
from __future__ import annotations

import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from ..http_client import new_session
from ..models import Publication, SourceCount

# Documenttypen die als overheidsakten worden meegeteld (sluit numac-nummers,
# uittreksels, berichten en index-items uit).
_ACT_KEYWORDS = [
    "besluit", "wet ", "loi ", "decreet", "décret",
    "ordonnantie", "ordonnance", "samenwerkingsakkoord", "accord de coopération",
    "koninklijk", "royal", "ministerieel", "ministériel",
    "programmawet", "financiewet", "reglement", "circulaire", "omzendbrief",
]

_EJUSTICE_BASE = "https://www.ejustice.just.fgov.be/cgi/"
_EJUSTICE_SUMMARY_URL = "https://www.ejustice.just.fgov.be/cgi/summary.pl?language=nl&sum_date={date}&s_editie={editie}&view_numac="


def _date_str_display(from_date: date, to_date: date) -> str:
    if from_date == to_date:
        return from_date.strftime("%d-%m-%Y")
    return f"{from_date.strftime('%d-%m-%Y')} t/m {to_date.strftime('%d-%m-%Y')}"


def fetch_belgisch_staatsblad(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """Belgisch Staatsblad via de ejustice inhoudstafel (summary.pl).

    De rech.pl zoekpagina vereist JavaScript; summary.pl geeft een statische
    inhoudstafel met alle article.pl-links per editie (1 en 2 per dag).
    """
    label = "BE Staatsblad"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""
    seen: set[str] = set()

    try:
        session = new_session()
        day = from_date
        while day <= to_date:
            date_str = day.strftime("%Y-%m-%d")
            for editie in (1, 2):
                url = _EJUSTICE_SUMMARY_URL.format(date=date_str, editie=editie)
                resp = session.get(url, timeout=20)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")

                for link_el in soup.select("a[href*='article.pl']"):
                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        href = _EJUSTICE_BASE + href.lstrip("/")
                    if href in seen:
                        continue
                    seen.add(href)

                    title = link_el.get_text(" ", strip=True)
                    if not title or len(title) < 5:
                        parent = link_el.find_parent(["td", "li", "div", "p"])
                        title = parent.get_text(" ", strip=True)[:250] if parent else ""
                    if len(title) < 10 or title.strip().isdigit():
                        continue

                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in _ACT_KEYWORDS):
                        continue

                    total += 1
                    result = matcher.match(title)
                    if result.relevant:
                        pubs.append(Publication(source="Belgisch Staatsblad", topic=result.topic, title=title[:250], url=href, pub_date=day))
            day = date.fromordinal(day.toordinal() + 1)
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    count = SourceCount(
        label=label, date_str=_date_str_display(from_date, to_date),
        relevant=len(pubs), total=total, api_error=api_error,
        note=error_note or "Telling via inhoudstafel (summary.pl), niet via de zoekpagina op ejustice.just.fgov.be — telling handmatig verifiëren",
    )
    return pubs, count


_REFLEX_BASE = "http://reflex.raadvst-consetat.be/reflex/"
_MONTH_NL = {
    1: "januari", 2: "februari", 3: "maart", 4: "april", 5: "mei", 6: "juni",
    7: "juli", 8: "augustus", 9: "september", 10: "oktober", 11: "november", 12: "december",
}


def fetch_reflex(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """refLex Chrono BE via de maandlijst (statische HTML, geen JavaScript nodig).

    De directe datumsearch op reflex.raadvst-consetat.be vereist JavaScript en
    geeft alleen historische navigatielinks terug bij een gewone HTTP-request.
    De maandlijst geeft echte documentlinks; we filteren op de dag in de titel
    (bijv. "... 14 augustus 2026 ..." of "14/08/2026").
    """
    label = "refLex Chrono BE"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""
    seen: set[str] = set()
    months_done: set[tuple[int, int]] = set()
    docs: dict[str, str] = {}

    try:
        session = new_session()
        day = from_date
        while day <= to_date:
            ym = (day.year, day.month)
            if ym not in months_done:
                months_done.add(ym)
                for page in range(1, 10):
                    if page == 1:
                        url = f"{_REFLEX_BASE}?page=chrono&c=list_get&d=list&year={day.year}&month={day.month}"
                    else:
                        url = f"{_REFLEX_BASE}index.reflex?page=chrono&c=lastsearch&d=list&pg={page}"
                    resp = session.get(url, timeout=20)
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "lxml")
                    detail_links = soup.select("a[href*='detail_get']")
                    if not detail_links:
                        break
                    for link_el in detail_links:
                        href = link_el.get("href", "")
                        if not href.startswith("http"):
                            href = _REFLEX_BASE + href.lstrip("?")
                        if href not in docs:
                            docs[href] = link_el.get_text(" ", strip=True)

            day_nl = str(day.day)
            month_str = _MONTH_NL[day.month]
            for href, title in docs.items():
                if href in seen:
                    continue
                title_lower = title.lower()
                if f" {day_nl} {month_str} {day.year}" in title_lower or f" {day_nl}/{day.month:02d}/{day.year}" in title:
                    seen.add(href)
                    total += 1
                    result = matcher.match(title)
                    if result.relevant:
                        pubs.append(Publication(source="refLex - Chrono", topic=result.topic, title=title, url=href, pub_date=day))
            day = date.fromordinal(day.toordinal() + 1)
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    count = SourceCount(
        label=label, date_str=_date_str_display(from_date, to_date),
        relevant=len(pubs), total=total, api_error=api_error,
        note=error_note or "Handmatig verifiëren op reflex.raadvst-consetat.be — telling kan afwijken",
    )
    return pubs, count


_JUSTEL_LIST_URL = (
    "https://www.ejustice.just.fgov.be/cgi_loi/list.pl"
    "?language=nl&pdd={pdd}&pdf={pdf}&page={page}"
)
_JUSTEL_ARTICLE_BASE = "https://www.ejustice.just.fgov.be/cgi_loi/"
_JUSTEL_ARTICLE_URL = _JUSTEL_ARTICLE_BASE + "article.pl?language=nl&caller=list&numac_search={numac}"
_JUSTEL_NUMAC_RE = re.compile(r"numac_search=([0-9A-Za-z]+)")
_JUSTEL_PAGE_SIZE = 30
_JUSTEL_MAX_PAGES = 20  # 600 akten; ruim boven elke week/maand

# Herpublicaties van reeds gepubliceerde akten als vertaling — geen nieuwe regelgeving.
_JUSTEL_TRANSLATION_MARKERS = (
    "duitse vertaling", "duitstalige vertaling", "traduction allemande",
    "franse vertaling", "vertaling in het duits",
)
_MONTH_NL_NUM = {name: num for num, name in _MONTH_NL.items()}


def _parse_justel_date(text: str) -> date | None:
    """'02 september 2026' / '5 augustus 2026' -> date."""
    m = re.match(r"\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text.strip())
    if not m:
        return None
    month = _MONTH_NL_NUM.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def fetch_justel(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """E-justice België (Justel) via de resultatenlijst list.pl (statische HTML).

    Justel is de genormeerde subset van het Belgisch Staatsblad (wetten, KB's,
    MB's, decreten, besluiten) met onderwerpsclassificatie per rij. list.pl
    filtert op publicatiedatum (pdd/pdf) en pagineert per 30. De Justel-index
    loopt enkele dagen achter op het Staatsblad, dus dit draait op weekcadans.
    """
    label = "E-justice België (Justel)"
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""
    skipped_translations = 0
    seen_numac: set[str] = set()

    try:
        session = new_session()
        for page in range(1, _JUSTEL_MAX_PAGES + 1):
            url = _JUSTEL_LIST_URL.format(pdd=from_date.isoformat(), pdf=to_date.isoformat(), page=page)
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            resp.encoding = "iso-8859-1"
            soup = BeautifulSoup(resp.text, "lxml")
            items = soup.select("div.list-item")
            if not items:
                break

            for item in items:
                link_el = item.select_one("a.list-item--title")
                if link_el is None:
                    continue
                title = link_el.get_text(" ", strip=True)
                if len(title) < 10:
                    continue

                href = link_el.get("href", "")
                numac_el = item.select_one("div.list-item--button a")
                numac = numac_el.get_text(strip=True) if numac_el else ""
                if not numac:
                    m = _JUSTEL_NUMAC_RE.search(href)
                    numac = m.group(1) if m else ""
                if numac:
                    if numac in seen_numac:
                        continue
                    seen_numac.add(numac)

                if any(mark in title.lower() for mark in _JUSTEL_TRANSLATION_MARKERS):
                    skipped_translations += 1
                    continue

                date_el = item.select_one("p.list-item--date")
                pub_dt = _parse_justel_date(date_el.get_text(strip=True)) if date_el else None
                if pub_dt is not None and not (from_date <= pub_dt <= to_date):
                    continue

                if numac:
                    href = _JUSTEL_ARTICLE_URL.format(numac=numac)
                elif not href.startswith("http"):
                    href = _JUSTEL_ARTICLE_BASE + href.lstrip("/")

                total += 1
                result = matcher.match(title)
                if result.relevant:
                    pubs.append(Publication(
                        source=label, topic=result.topic, title=title[:250],
                        url=href, pub_date=pub_dt or from_date,
                    ))

            if len(items) < _JUSTEL_PAGE_SIZE:
                break
            time.sleep(0.2)
    except requests.RequestException as exc:
        api_error = True
        error_note = str(exc)

    note = error_note or "Justel-index loopt enkele dagen achter op het Belgisch Staatsblad — draai zo nodig ook de voorgaande week"
    if skipped_translations and not error_note:
        note = f"{skipped_translations} vertaal-herpublicaties overgeslagen. {note}"

    count = SourceCount(
        label=label, date_str=_date_str_display(from_date, to_date),
        relevant=len(pubs), total=total, api_error=api_error, note=note,
    )
    return pubs, count

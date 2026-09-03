"""EUR-Lex via de CELLAR SPARQL-API van het EU Publications Office.

De EUR-Lex website zelf blokkeert geautomatiseerde toegang (AWS WAF); CELLAR
biedt dezelfde data via een officieel SPARQL-eindpunt. Verified live and
working (2026-08-17) — this is the more robust of the government sources.
"""
from __future__ import annotations

from datetime import date

import requests

from ..models import Publication, SourceCount

_CELLAR_SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"

_OJ_QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?eli ?title WHERE {{
  ?work cdm:official-journal-act_date_publication "{date}"^^xsd:date ;
        cdm:resource_legal_eli ?eli .
  FILTER(
    STRSTARTS(STR(?eli), "http://data.europa.eu/eli/") &&
    STRENDS(STR(?eli), "/oj")
  )
  OPTIONAL {{
    ?expr cdm:expression_belongs_to_work ?work ;
          cdm:expression_uses_language
            <http://publications.europa.eu/resource/authority/language/ENG> ;
          cdm:expression_title ?title .
  }}
}}
ORDER BY ?eli"""

_PREACTS_QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?title ?date WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER({prefix_filter})
  ?work cdm:work_date_document ?date .
  FILTER(?date >= "{from_date}"^^xsd:date && ?date <= "{to_date}"^^xsd:date)
  {nl_filter}
  OPTIONAL {{
    ?expr cdm:expression_belongs_to_work ?work ;
          cdm:expression_uses_language
            <http://publications.europa.eu/resource/authority/language/ENG> ;
          cdm:expression_title ?title .
  }}
}}
ORDER BY ?date ?celex"""

_EURLEX_OJ_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:{series}:{year}:{number}"
_EURLEX_CELEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"


def _run_sparql(query: str) -> list[dict]:
    resp = requests.post(
        _CELLAR_SPARQL_URL,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", {}).get("bindings", [])


def fetch_eurlex_oj(label: str, series: str, from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """OJ L (wetgeving) of OJ C (mededelingen), o.b.v. /eli/C/ in de ELI.

    OJ C-acts hebben /eli/C/ in hun ELI; alle overige zijn OJ L.
    """
    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""

    day = from_date
    try:
        while day <= to_date:
            bindings = _run_sparql(_OJ_QUERY.format(date=day.isoformat()))
            for b in bindings:
                eli = b.get("eli", {}).get("value", "")
                title = b.get("title", {}).get("value", "")
                is_c = "/eli/C/" in eli
                if (series == "C") != is_c:
                    continue
                total += 1
                if not title:
                    continue
                result = matcher.match(title)
                if result.relevant:
                    parts = eli.removesuffix("/oj").rsplit("/", 2)
                    year, number = (parts[-2], parts[-1]) if len(parts) >= 2 else (str(day.year), "")
                    url = _EURLEX_OJ_URL.format(series=series, year=year, number=number)
                    pubs.append(Publication(source=label, topic=result.topic, title=title, url=url, pub_date=day))
            day = date.fromordinal(day.toordinal() + 1)
    except requests.RequestException as exc:
        api_error = True
        error_note = f"[CELLAR FOUT] {exc}"

    count = SourceCount(
        label=label,
        date_str=f"{from_date.isoformat()} t/m {to_date.isoformat()}" if from_date != to_date else from_date.isoformat(),
        relevant=len(pubs), total=total, api_error=api_error, note=error_note,
    )
    return pubs, count


def _fetch_cellar_preacts(
    label: str,
    celex_prefixes: list[str],
    from_date: date,
    to_date: date,
    matcher,
    require_nl: bool = True,
) -> tuple[list[Publication], SourceCount]:
    """celex_prefixes: bijv. ["52026PC", "52026DC"] voor COM-documenten.

    require_nl=False voor documenten (zoals SWD) die zelden in het Nederlands
    worden vertaald; dan volstaat de Engelse titel voor keyword-matching.
    """
    prefix_filter = " || ".join(f'STRSTARTS(?celex, "{p}")' for p in celex_prefixes)
    nl_filter = ""
    if require_nl:
        nl_filter = (
            "FILTER(EXISTS { ?nl_expr cdm:expression_belongs_to_work ?work ; "
            "cdm:expression_uses_language "
            "<http://publications.europa.eu/resource/authority/language/NLD> . })"
        )
    query = _PREACTS_QUERY.format(
        prefix_filter=prefix_filter, from_date=from_date.isoformat(),
        to_date=to_date.isoformat(), nl_filter=nl_filter,
    )

    pubs: list[Publication] = []
    total = 0
    api_error = False
    error_note = ""
    try:
        bindings = _run_sparql(query)
        total = len(bindings)
        for b in bindings:
            celex = b.get("celex", {}).get("value", "")
            title = b.get("title", {}).get("value", "")
            date_str = b.get("date", {}).get("value", "")
            if not title:
                continue
            result = matcher.match(title)
            if result.relevant:
                try:
                    pub_date = date.fromisoformat(date_str)
                except ValueError:
                    pub_date = None
                pubs.append(Publication(
                    source=label, topic=result.topic, title=title,
                    url=_EURLEX_CELEX_URL.format(celex=celex), pub_date=pub_date,
                ))
    except requests.RequestException as exc:
        api_error = True
        error_note = f"[CELLAR FOUT] {exc}"

    count = SourceCount(
        label=label,
        date_str=f"{from_date.isoformat()} t/m {to_date.isoformat()}" if from_date != to_date else from_date.isoformat(),
        relevant=len(pubs), total=total, api_error=api_error, note=error_note,
    )
    return pubs, count


def fetch_com_documents(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """COM-documenten: alleen echte voorstellen (PC) en documenten (DC). Geen OJ C-berichten."""
    year = to_date.year
    return _fetch_cellar_preacts("COM-documenten", [f"5{year}PC", f"5{year}DC"], from_date, to_date, matcher, require_nl=True)


def fetch_join_documents(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """JOIN-documenten: gezamenlijke voorstellen Commissie + Hoge Vertegenwoordiger."""
    year = to_date.year
    return _fetch_cellar_preacts("JOIN-documenten", [f"5{year}JC"], from_date, to_date, matcher, require_nl=True)


def fetch_swd_documents(from_date: date, to_date: date, matcher) -> tuple[list[Publication], SourceCount]:
    """SEC/SWD – Staff Working Documents worden niet in het Nederlands vertaald; alleen ENG titel."""
    year = to_date.year
    return _fetch_cellar_preacts("SEC/SWD", [f"5{year}SC"], from_date, to_date, matcher, require_nl=False)

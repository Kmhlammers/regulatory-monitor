"""CLI entry point, rebuilt from regulatory_monitor.py's argparse setup and print_summary."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from .config import load_config
from .export import export_counts_csv, export_json, export_publications_csv
from .matching import RelevanceMatcher
from .pipeline import DAILY_SOURCES, EXPERIMENTAL_WEEKLY_SOURCES, WEEKLY_SOURCES, deduplicate, run_sources


def week_to_dates(week_nr: int, year: int) -> tuple[date, date]:
    """Geeft maandag en zondag van een ISO-weeknummer terug."""
    monday = date.fromisocalendar(year, week_nr, 1)
    sunday = date.fromisocalendar(year, week_nr, 7)
    return monday, sunday


def print_summary(publications, counts, checked_range: str, antidumping_hits) -> None:
    print("=" * 65)
    print(f" Publicatiedatum: {checked_range}")
    print("=" * 65)
    print()
    print("=" * 80)
    print("  TELLINGEN PER BRON  (x relevant / y gecontroleerd)")
    print("=" * 80)
    for c in counts:
        ratio = "[API FOUT]" if c.api_error else (f"{c.relevant}/{c.total}" if (c.total or c.relevant) else "—")
        note = f"  ({c.note})" if c.note else ""
        print(f"  {c.label:55s} {ratio:>10s}{note}")
    print()

    if publications:
        print(f"  RELEVANTE PUBLICATIES  ({len(publications)} totaal)")
        print("-" * 80)
        for p in sorted(publications, key=lambda p: p.pub_date or date.min, reverse=True):
            datum = p.pub_date.strftime("%d-%m-%Y") if p.pub_date else "—"
            print(f"  [{p.topic}] {datum} — {p.title}")
            print(f"    {p.url}")
    else:
        print("  Geen relevante publicaties gevonden.")

    if antidumping_hits:
        print()
        print(f"  ANTI-DUMPING SIGNALERINGEN  ({len(antidumping_hits)}, doorsturen naar team)")
        print("-" * 80)
        for source, title, url in antidumping_hits:
            print(f"  [{source}] {title}\n    {url}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regulatory Monitor – Non-food EU/NL/BE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=["daily", "weekly", "both"], default="both")

    daily_group = parser.add_argument_group("Dagelijkse check – datumbereik")
    daily_group.add_argument("--from", dest="date_from", help="Publicatiedatum van (default: gisteren = YYYY-MM-DD)")
    daily_group.add_argument("--to", dest="date_to", help="Publicatiedatum t/m (default: zelfde als --from)")

    weekly_group = parser.add_argument_group("Wekelijkse check – weeknummer")
    weekly_group.add_argument("--week", type=int, help="ISO-weeknummer (default: huidige week)")
    weekly_group.add_argument("--year", type=int, help="Jaar (default: huidig jaar)")

    parser.add_argument("--output", default="regulatory_results", help="Basisnaam outputbestanden")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="csv")
    parser.add_argument("--experimental", action="store_true", help="Voeg experimentele bronnen toe (CEN/CENELEC, FOD Economie, RVO, SCCS, EUON, EFSA)")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = load_config()
    matcher = RelevanceMatcher(config)

    all_pubs = []
    all_counts = []
    checked_ranges = []
    exp_sources = set(EXPERIMENTAL_WEEKLY_SOURCES) if args.experimental else set()

    if args.mode in ("daily", "both"):
        yesterday = date.today() - timedelta(days=1)
        daily_from = date.fromisoformat(args.date_from) if args.date_from else yesterday
        daily_to = date.fromisoformat(args.date_to) if args.date_to else daily_from
        pubs, counts = run_sources(DAILY_SOURCES, daily_from, daily_to, matcher, week="")
        all_pubs.extend(pubs)
        all_counts.extend(counts)
        checked_ranges.append(f"DAGELIJKSE CHECK {daily_from.isoformat()} t/m {daily_to.isoformat()}")

    if args.mode in ("weekly", "both"):
        current_week = date.today().isocalendar()[1]
        current_year = date.today().isocalendar()[0]
        week_nr = args.week or current_week
        year = args.year or current_year
        weekly_from, weekly_to = week_to_dates(week_nr, year)
        sources = WEEKLY_SOURCES + (list(EXPERIMENTAL_WEEKLY_SOURCES) if args.experimental else [])
        pubs, counts = run_sources(sources, weekly_from, weekly_to, matcher, week=f"{year}-W{week_nr:02d}", experimental_labels=exp_sources)
        all_pubs.extend(pubs)
        all_counts.extend(counts)
        suffix = " (incl. experimenteel)" if args.experimental else ""
        checked_ranges.append(f"WEKELIJKSE CHECK week {week_nr} ({year}){suffix}")

    unique_pubs = deduplicate(all_pubs)
    antidumping_hits = [
        (p.source, p.title, p.url) for p in unique_pubs if matcher.is_antidumping(p.title)
    ]

    print_summary(unique_pubs, all_counts, " / ".join(checked_ranges), antidumping_hits)

    if args.format in ("csv", "both"):
        export_publications_csv(unique_pubs, f"{args.output}.csv")
        export_counts_csv(all_counts, f"{args.output}_tellingen.csv", config.manual_check_notes)
    if args.format in ("json", "both"):
        export_json(unique_pubs, f"{args.output}.json")


if __name__ == "__main__":
    main()

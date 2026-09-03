"""CSV/JSON export, mirroring the two output files the original CLI produced:
regulatory_results.csv ('Algemene controle' tab) and regulatory_counts.csv
(Daily/Weekly tab)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Publication, SourceCount


def export_publications_csv(publications: list[Publication], path: Path | str, checked_dates: set | None = None) -> None:
    """CSV voor 'Algemene controle' tab. Behoudt entries buiten de gecheckte datumrange
    door bestaande rijen met een datum buiten checked_dates over te nemen."""
    path = Path(path)
    fieldnames = ["Week", "Onderwerp", "Titel", "Link", "Publicatie datum"]
    existing_rows = []
    if checked_dates and path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row.get("Publicatie datum", "") not in checked_dates:
                    existing_rows.append(row)

    new_rows = [
        {
            "Week": p.week,
            "Onderwerp": p.topic,
            "Titel": p.title,
            "Link": p.url,
            "Publicatie datum": p.pub_date.strftime("%d-%m-%Y") if p.pub_date else "",
        }
        for p in publications
    ]

    all_rows = existing_rows + new_rows
    all_rows.sort(key=lambda r: r.get("Publicatie datum", ""), reverse=True)

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"  Publicaties CSV: {path} ({len(all_rows)} rijen)")


def export_counts_csv(counts: list[SourceCount], path: Path | str, manual_check_notes: dict[str, str]) -> None:
    """CSV met x/y tellingen per bron voor de Daily/Weekly tab."""
    path = Path(path)
    fieldnames = ["Bron", "Datum/periode", "Relevant (non-food)", "Opmerking"]
    rows = []
    for c in counts:
        if c.api_error:
            ratio = "API FOUT — handmatig checken op officielebekendmakingen.nl"
        elif c.total == 0 and c.relevant == 0:
            ratio = "n.v.t."
        else:
            ratio = f"{c.relevant}/{c.total}"
        note = manual_check_notes.get(c.label, c.note)
        rows.append({"Bron": c.label, "Datum/periode": c.date_str, "Relevant (non-food)": ratio, "Opmerking": note})

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Tellingen CSV:   {path} ({len(rows)} bronnen)")


def export_json(publications: list[Publication], path: Path | str) -> None:
    path = Path(path)
    data = {
        "publications": [
            {
                "source": p.source,
                "topic": p.topic,
                "title": p.title,
                "url": p.url,
                "pub_date": p.pub_date.isoformat() if p.pub_date else None,
                "week": p.week,
            }
            for p in publications
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  JSON:            {path}")

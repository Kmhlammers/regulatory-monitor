"""Runs the Regulatory Monitor pipeline and (re)builds the static GitHub Pages site.

Usage:
    python build_site.py daily                 # previous day(s), auto gap-fill
    python build_site.py daily --date 2026-09-02
    python build_site.py daily --from 2026-08-30 --to 2026-09-02
    python build_site.py weekly                 # previous ISO week
    python build_site.py weekly --week 35 --year 2026
    python build_site.py rebuild               # regenerate HTML from data/, no fetching

Each run is stored as JSON under data/{daily,weekly}/; the whole public/ site is
regenerated from every stored run so the archive stays reproducible.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Amsterdam")
except Exception:  # pragma: no cover - fallback if tzdata missing
    TZ = timezone.utc

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from regulatory_monitor.cli import week_to_dates  # noqa: E402
from regulatory_monitor.config import load_config  # noqa: E402
from regulatory_monitor.matching import RelevanceMatcher  # noqa: E402
from regulatory_monitor.pipeline import (  # noqa: E402
    DAILY_SOURCES,
    WEEKLY_SOURCES,
    deduplicate,
    run_sources,
)

DATA_DIR = ROOT / "data"
PUBLIC_DIR = ROOT / "public"
MAX_DAILY_BACKFILL_DAYS = 6

NL_MONTHS = [
    "", "januari", "februari", "maart", "april", "mei", "juni", "juli",
    "augustus", "september", "oktober", "november", "december",
]

GREEN = "#2D5016"
ORANGE = "#b5651d"


# --------------------------------------------------------------------------- #
# Pipeline runs                                                                #
# --------------------------------------------------------------------------- #

def _nl_date(d: date) -> str:
    return f"{d.day} {NL_MONTHS[d.month]} {d.year}"


def _range_label(frm: date, to: date) -> str:
    if frm == to:
        return _nl_date(to)
    if (frm.month, frm.year) == (to.month, to.year):
        return f"{frm.day}–{to.day} {NL_MONTHS[to.month]} {to.year}"
    return f"{_nl_date(frm)} – {_nl_date(to)}"


def _pub_to_dict(p) -> dict:
    return {
        "source": p.source,
        "topic": p.topic,
        "title": p.title,
        "url": p.url,
        "pub_date": p.pub_date.isoformat() if p.pub_date else None,
        "week": p.week,
    }


def _count_to_dict(c) -> dict:
    return {
        "label": c.label,
        "date_str": c.date_str,
        "relevant": c.relevant,
        "total": c.total,
        "api_error": c.api_error,
        "note": c.note,
    }


def run_daily(frm: date, to: date, matcher: RelevanceMatcher) -> dict:
    pubs, counts = run_sources(DAILY_SOURCES, frm, to, matcher, week="")
    unique = deduplicate(pubs)
    antidumping = [p for p in unique if matcher.is_antidumping(p.title)]
    return {
        "kind": "daily",
        "id": to.isoformat(),
        "label": _range_label(frm, to),
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publications": [_pub_to_dict(p) for p in unique],
        "counts": [_count_to_dict(c) for c in counts],
        "antidumping": [{"source": p.source, "title": p.title, "url": p.url} for p in antidumping],
    }


def run_weekly(week: int, year: int, matcher: RelevanceMatcher) -> dict:
    frm, to = week_to_dates(week, year)
    label = f"{year}-W{week:02d}"
    pubs, counts = run_sources(WEEKLY_SOURCES, frm, to, matcher, week=label)
    unique = deduplicate(pubs)
    antidumping = [p for p in unique if matcher.is_antidumping(p.title)]
    return {
        "kind": "weekly",
        "id": label,
        "label": f"week {week} · {year}",
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publications": [_pub_to_dict(p) for p in unique],
        "counts": [_count_to_dict(c) for c in counts],
        "antidumping": [{"source": p.source, "title": p.title, "url": p.url} for p in antidumping],
    }


def save_run(run: dict) -> Path:
    out_dir = DATA_DIR / run["kind"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run['id']}.json"
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_runs(kind: str) -> list[dict]:
    out_dir = DATA_DIR / kind
    if not out_dir.is_dir():
        return []
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in out_dir.glob("*.json")]
    runs.sort(key=lambda r: (r.get("to", ""), r.get("id", "")), reverse=True)
    return runs


def default_daily_range() -> tuple[date, date]:
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    prior = [date.fromisoformat(r["to"]) for r in load_runs("daily")]
    last = max(prior) if prior else None
    if last is None or last >= yesterday:
        return yesterday, yesterday
    start = max(last + timedelta(days=1), yesterday - timedelta(days=MAX_DAILY_BACKFILL_DAYS))
    return start, yesterday


def default_weekly() -> tuple[int, int]:
    d = datetime.now(TZ).date() - timedelta(days=7)
    year, week, _ = d.isocalendar()
    return week, year


# --------------------------------------------------------------------------- #
# Site rendering                                                               #
# --------------------------------------------------------------------------- #

CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     color:#1a1a1a;background:#f7f7f7;line-height:1.5}}
a{{color:{GREEN}}}
.pc-header{{background:{GREEN};padding:1.3rem 2rem;display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap}}
.pc-header h1{{color:#fff;font-size:1.2rem;font-weight:600;margin:0}}
.pc-header a{{color:rgba(255,255,255,.75);font-size:.85rem;text-decoration:none}}
.pc-header a:hover{{color:#fff}}
.pc-wrap{{max-width:1000px;margin:0 auto;padding:2rem 1.5rem 4rem}}
.pc-lead{{color:#555;font-size:.9rem;margin:.2rem 0 2rem}}
.pc-section{{color:{GREEN};font-weight:600;font-size:1rem;border-bottom:2px solid {GREEN};
            padding-bottom:.35rem;margin:2.4rem 0 1rem}}
.pc-section:first-of-type{{margin-top:0}}
.pc-sub{{color:#666;font-size:.82rem;margin:-.6rem 0 1rem}}
table{{width:100%;border-collapse:collapse;font-size:.83rem;background:#fff;
       border:1px solid #e0e0e0;border-radius:4px;overflow:hidden}}
th,td{{text-align:left;padding:.5rem .7rem;border-bottom:1px solid #eee;vertical-align:top}}
th{{background:#eef3e8;color:{GREEN};font-weight:600}}
tr:last-child td{{border-bottom:none}}
td.num{{white-space:nowrap;font-variant-numeric:tabular-nums}}
.err{{color:#b00}}
.pc-card{{background:#fff;border:1px solid #e0e0e0;border-left:4px solid {GREEN};
         border-radius:4px;padding:.8rem 1rem;margin-bottom:.55rem}}
.pc-card.ad{{border-left-color:{ORANGE}}}
.pc-card .topic{{font-weight:600;font-size:.86rem;color:{GREEN}}}
.pc-card.ad .topic{{color:{ORANGE}}}
.pc-card .date{{color:#666;font-size:.8rem}}
.pc-card .title{{font-size:.9rem;margin:.3rem 0 .4rem}}
.pc-card .src{{color:#888;font-size:.76rem}}
.pc-card a.go{{font-size:.82rem;text-decoration:none}}
.pc-card a.go:hover{{text-decoration:underline}}
.pc-empty{{color:#666;font-size:.9rem;padding:1.5rem 0}}
.pc-warn{{background:#fffbea;border:1px solid #f0d070;border-radius:4px;padding:.7rem 1rem;
         font-size:.83rem;color:#6b5300;margin:1rem 0}}
.pc-archive-list{{list-style:none;padding:0;margin:0}}
.pc-archive-list li{{background:#fff;border:1px solid #e0e0e0;border-radius:4px;
                    padding:.6rem .9rem;margin-bottom:.45rem;display:flex;justify-content:space-between;
                    gap:1rem;font-size:.88rem;flex-wrap:wrap}}
.pc-archive-list .meta{{color:#888;font-size:.8rem}}
.pc-foot{{margin-top:3rem;padding-top:1rem;border-top:1px solid #e0e0e0;color:#888;font-size:.78rem}}
.pc-cols{{display:grid;grid-template-columns:1fr 1fr;gap:2rem}}
@media(max-width:720px){{.pc-cols{{grid-template-columns:1fr}}}}
"""


def _page(title: str, body: str, depth: int) -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="pc-header">
  <h1>Non-food Regulatory Monitor</h1>
  <a href="{up}index.html">Overzicht</a>
  <a href="{up}archief.html">Archief</a>
</div>
<div class="pc-wrap">
{body}
<div class="pc-foot">Précon &middot; automatisch gegenereerd &middot; alle bronnen zijn openbare publicatiebladen en overheidssites.</div>
</div>
</body>
</html>
"""


def _counts_table(counts: list[dict], notes: dict[str, str]) -> str:
    rows = []
    for c in counts:
        if c["api_error"]:
            ratio = '<span class="err">&#9888; API fout</span>'
        elif c["total"] == 0 and c["relevant"] == 0:
            ratio = "&mdash;"
        else:
            ratio = f"{c['relevant']}/{c['total']}"
        note = notes.get(c["label"], c["note"]) or ""
        rows.append(
            f"<tr><td>{escape(c['label'])}</td><td class='num'>{escape(c['date_str'])}</td>"
            f"<td class='num'>{ratio}</td><td>{escape(note)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Bron</th><th>Periode</th><th>Relevant / totaal</th>"
        "<th>Opmerking</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _pub_card(p: dict, antidumping: bool = False) -> str:
    cls = "pc-card ad" if antidumping else "pc-card"
    if p.get("pub_date"):
        d = date.fromisoformat(p["pub_date"])
        datum = _nl_date(d)
    else:
        datum = "—"
    topic = (p.get("topic") or "").replace("[EXP] ", "")
    return (
        f"<div class='{cls}'>"
        f"<span class='topic'>{escape(topic)}</span> "
        f"<span class='date'>&middot; {escape(datum)}</span>"
        f"<div class='title'>{escape(p['title'])}</div>"
        f"<div class='src'>{escape(p.get('source', ''))}</div>"
        f"<a class='go' href='{escape(p['url'], quote=True)}' target='_blank' rel='noopener'>&#8599; Bekijk publicatie</a>"
        f"</div>"
    )


def _report_body(run: dict, notes: dict[str, str], heading: str) -> str:
    pubs = sorted(
        run["publications"],
        key=lambda p: p.get("pub_date") or "",
        reverse=True,
    )
    gen = datetime.fromisoformat(run["generated_at"]).astimezone(TZ)
    parts = [
        f"<div class='pc-section'>{escape(heading)}</div>",
        f"<div class='pc-sub'>Periode {escape(_range_label(date.fromisoformat(run['from']), date.fromisoformat(run['to'])))} "
        f"&middot; gedraaid {gen.strftime('%d-%m-%Y %H:%M')}</div>",
        "<div class='pc-section'>Tellingen per bron</div>",
        _counts_table(run["counts"], notes),
    ]

    run_labels = {c["label"] for c in run["counts"]}
    manual = [lbl for lbl, note in notes.items() if note and lbl in run_labels]
    if manual:
        parts.append(
            f"<div class='pc-warn'>&#9888; Handmatig checken (bron niet automatiseerbaar): "
            f"{escape(', '.join(manual))}</div>"
        )

    parts.append(f"<div class='pc-section'>Relevante publicaties ({len(pubs)})</div>")
    if pubs:
        parts.append("".join(_pub_card(p) for p in pubs))
    else:
        parts.append("<div class='pc-empty'>Geen relevante publicaties gevonden.</div>")

    if run["antidumping"]:
        parts.append(f"<div class='pc-section'>Anti-dumping signaleringen ({len(run['antidumping'])})</div>")
        parts.append("".join(_pub_card(p, antidumping=True) for p in run["antidumping"]))

    return "\n".join(parts)


def build_site() -> None:
    config = load_config()
    notes = config.manual_check_notes

    daily = load_runs("daily")
    weekly = load_runs("weekly")

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (PUBLIC_DIR / "dag").mkdir(exist_ok=True)
    (PUBLIC_DIR / "week").mkdir(exist_ok=True)

    # Individual report pages
    for run in daily:
        heading = f"Dagelijkse rapportage — {run['label']}"
        html = _page(f"{heading} | Regulatory Monitor", _report_body(run, notes, heading), depth=1)
        (PUBLIC_DIR / "dag" / f"{run['id']}.html").write_text(html, encoding="utf-8")
    for run in weekly:
        heading = f"Weekrapportage — {run['label']}"
        html = _page(f"{heading} | Regulatory Monitor", _report_body(run, notes, heading), depth=1)
        (PUBLIC_DIR / "week" / f"{run['id']}.html").write_text(html, encoding="utf-8")

    # Landing page: latest of each
    body_parts = [
        "<p class='pc-lead'>Nederlandse, Belgische en EU-bronnen op relevante regelgevingswijzigingen "
        "voor non-food. Automatisch bijgewerkt — dagelijks op werkdagen, wekelijks op maandag.</p>"
    ]
    if daily:
        body_parts.append(_report_body(daily[0], notes, f"Laatste dagelijkse rapportage — {daily[0]['label']}"))
        body_parts.append(f"<p><a href='dag/{daily[0]['id']}.html'>Vaste link naar deze rapportage &#8599;</a></p>")
    if weekly:
        body_parts.append(_report_body(weekly[0], notes, f"Laatste weekrapportage — {weekly[0]['label']}"))
        body_parts.append(f"<p><a href='week/{weekly[0]['id']}.html'>Vaste link naar deze rapportage &#8599;</a></p>")
    if not daily and not weekly:
        body_parts.append("<div class='pc-empty'>Nog geen rapportages gegenereerd.</div>")
    body_parts.append("<p style='margin-top:2rem'><a href='archief.html'>Volledig archief &#8594;</a></p>")
    (PUBLIC_DIR / "index.html").write_text(
        _page("Non-food Regulatory Monitor | Précon", "\n".join(body_parts), depth=0),
        encoding="utf-8",
    )

    # Archive
    def _archive_col(title: str, runs: list[dict], sub: str) -> str:
        items = "".join(
            f"<li><a href='{sub}/{r['id']}.html'>{escape(r['label'])}</a>"
            f"<span class='meta'>{len(r['publications'])} relevant</span></li>"
            for r in runs
        ) or "<li class='meta'>Nog geen rapportages.</li>"
        return f"<div><div class='pc-section'>{escape(title)}</div><ul class='pc-archive-list'>{items}</ul></div>"

    archive_body = (
        "<div class='pc-cols'>"
        + _archive_col("Dagelijkse rapportages", daily, "dag")
        + _archive_col("Weekrapportages", weekly, "week")
        + "</div>"
    )
    (PUBLIC_DIR / "archief.html").write_text(
        _page("Archief | Regulatory Monitor", archive_body, depth=0), encoding="utf-8"
    )

    print(f"  Site gebouwd: {len(daily)} dagelijkse + {len(weekly)} wekelijkse rapportages -> {PUBLIC_DIR}")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_daily = sub.add_parser("daily", help="Draai dagelijkse check en herbouw de site")
    p_daily.add_argument("--date", help="Eén dag (YYYY-MM-DD)")
    p_daily.add_argument("--from", dest="date_from", help="Begin datumbereik (YYYY-MM-DD)")
    p_daily.add_argument("--to", dest="date_to", help="Eind datumbereik (YYYY-MM-DD)")

    p_weekly = sub.add_parser("weekly", help="Draai wekelijkse check en herbouw de site")
    p_weekly.add_argument("--week", type=int, help="ISO-weeknummer")
    p_weekly.add_argument("--year", type=int, help="Jaar")

    sub.add_parser("rebuild", help="Herbouw alleen de HTML uit data/, zonder bronnen te bevragen")

    args = parser.parse_args(argv)

    if args.cmd == "rebuild":
        build_site()
        return

    matcher = RelevanceMatcher(load_config())

    if args.cmd == "daily":
        if args.date:
            frm = to = date.fromisoformat(args.date)
        elif args.date_from:
            frm = date.fromisoformat(args.date_from)
            to = date.fromisoformat(args.date_to) if args.date_to else frm
        else:
            frm, to = default_daily_range()
        print(f"Dagelijkse check {frm.isoformat()} t/m {to.isoformat()}")
        run = run_daily(frm, to, matcher)
    else:
        if args.week:
            week, year = args.week, args.year or datetime.now(TZ).year
        else:
            week, year = default_weekly()
        print(f"Wekelijkse check week {week} ({year})")
        run = run_weekly(week, year, matcher)

    path = save_run(run)
    print(f"  Run opgeslagen: {path}  ({len(run['publications'])} relevante publicaties)")
    build_site()


if __name__ == "__main__":
    main()

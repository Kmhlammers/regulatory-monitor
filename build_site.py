"""Runs the Regulatory Monitor pipeline and (re)builds the static GitHub Pages site.

Usage:
    python build_site.py daily                 # previous day(s), auto gap-fill
    python build_site.py daily --date 2026-09-02
    python build_site.py daily --from 2026-08-30 --to 2026-09-02
    python build_site.py weekly                 # previous ISO week
    python build_site.py weekly --week 35 --year 2026
    python build_site.py rebuild               # regenerate the site from data/, no fetching

Each run is stored as JSON under data/{daily,weekly}/. The site is a single page
(index.html + app.js) that reads every stored run from runs.js and lets you switch
between day and week reports client-side.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
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


def _build_run(kind: str, run_id: str, label: str, frm: date, to: date, unique, counts, matcher) -> dict:
    antidumping = [p for p in unique if matcher.is_antidumping(p.title)]
    return {
        "kind": kind,
        "id": run_id,
        "label": label,
        "from": frm.isoformat(),
        "to": to.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publications": [_pub_to_dict(p) for p in unique],
        "counts": [_count_to_dict(c) for c in counts],
        "antidumping": [{"source": p.source, "title": p.title, "url": p.url} for p in antidumping],
    }


def run_daily(frm: date, to: date, matcher: RelevanceMatcher) -> dict:
    pubs, counts = run_sources(DAILY_SOURCES, frm, to, matcher, week="")
    unique = deduplicate(pubs)
    return _build_run("daily", to.isoformat(), _range_label(frm, to), frm, to, unique, counts, matcher)


def run_weekly(week: int, year: int, matcher: RelevanceMatcher) -> dict:
    frm, to = week_to_dates(week, year)
    label = f"{year}-W{week:02d}"
    pubs, counts = run_sources(WEEKLY_SOURCES, frm, to, matcher, week=label)
    unique = deduplicate(pubs)
    return _build_run("weekly", label, f"week {week} · {year}", frm, to, unique, counts, matcher)


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
# Site (single page; data in runs.js, rendering in app.js)                     #
# --------------------------------------------------------------------------- #

INDEX_HTML = """<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Regulatory Monitor — Précon</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Overpass:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --navy:#003855; --navy-soft:#1c4a63;
  --orange:#fa6401; --orange-dark:#d9590a; --orange-deep:#b4530a; --orange-tint:#fdf3ea;
  --slate:#334f66; --slate-soft:#66798d; --gray:#8895a5;
  --line:#dfe4ec; --line-soft:#e7ebf1;
  --bg:#eff0f5; --card:#fff; --panel:#fbfcfe;
  --shadow:0 8px 24px rgba(0,56,85,.07);
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--slate);font-family:'Overpass',system-ui,sans-serif;line-height:1.5}
a{color:var(--orange-dark);text-decoration:none}
a:hover{text-decoration:underline}
h1,h2,h3{font-family:'Libre Baskerville','Georgia',serif;color:var(--navy);font-weight:700}

.topbar{position:sticky;top:0;z-index:20;background:rgba(239,240,245,.92);
  backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
.topbar-inner{max-width:960px;margin:0 auto;padding:15px 24px;display:flex;align-items:baseline;gap:12px}
.brand{font-family:'Libre Baskerville',serif;font-weight:700;font-size:21px;color:var(--navy)}
.brand span{font-family:'Overpass',sans-serif;font-weight:500;font-size:13px;color:var(--slate-soft);margin-left:4px}

.wrap{max-width:960px;margin:0 auto;padding:26px 24px 90px}

.overview{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:26px}
.ov-tile{text-align:left;background:var(--card);border:1px solid var(--line);border-radius:14px;
  box-shadow:var(--shadow);padding:16px 18px;cursor:pointer;font:inherit;color:inherit;
  display:flex;flex-direction:column;gap:3px;transition:border-color .15s,box-shadow .15s}
.ov-tile:hover{border-color:var(--orange-soft,#f5a554)}
.ov-tile.active{border:1.5px solid var(--navy);box-shadow:0 8px 24px rgba(0,56,85,.12)}
.ov-label{font-size:12px;font-weight:600;letter-spacing:1.3px;text-transform:uppercase;color:var(--gray)}
.ov-date{font-size:15px;font-weight:600;color:var(--navy)}
.ov-count{font-family:'Libre Baskerville',serif;font-size:26px;color:var(--orange-dark);line-height:1.1;margin-top:2px}
.ov-count small{font-family:'Overpass',sans-serif;font-size:13px;font-weight:500;color:var(--slate-soft)}

.navrow{display:flex;align-items:center;gap:10px;margin-bottom:22px;flex-wrap:wrap}
.navrow .arrow{width:38px;height:38px;flex-shrink:0;border-radius:50%;border:1.5px solid var(--navy);
  background:#fff;color:var(--navy);cursor:pointer;font-size:15px;line-height:1}
.navrow .arrow:disabled{opacity:.3;cursor:default}
.navrow select{flex:1;min-width:180px;max-width:340px;border:1.5px solid var(--navy);border-radius:22px;
  padding:8px 16px;font:inherit;font-weight:600;color:var(--navy);background:#fff;cursor:pointer}

.report-head{margin-bottom:6px}
.report-head h1{font-size:29px;margin:0}
.report-sub{font-size:14px;color:var(--slate-soft);margin-top:2px}

.statline{margin:18px 0 8px;font-size:15px;color:var(--slate-soft)}
.statline .stat{font-family:'Libre Baskerville',serif;font-size:22px;color:var(--orange-dark);margin-right:3px}
.statline .stat-ad{font-family:'Libre Baskerville',serif;font-size:22px;color:var(--navy);margin:0 3px}

.section-title{font-size:19px;margin:38px 0 14px;padding-bottom:7px;border-bottom:1px solid var(--line)}

.card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);
  padding:15px 17px;margin-bottom:11px}
.card.ad{border-left:3px solid var(--orange)}
.card-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pill{display:inline-block;border:1.5px solid var(--orange);color:var(--orange-deep);border-radius:14px;
  padding:2px 10px;font-size:12px;font-weight:600}
.card .date{color:var(--gray);font-size:13px}
.card .title{font-size:15.5px;color:var(--slate);margin:.4rem 0 .3rem;line-height:1.45}
.card .src{color:var(--gray);font-size:12.5px;margin-bottom:.5rem}
.card a.go{font-size:13.5px;font-weight:600}

.warn{background:var(--orange-tint);border:1px solid #f1d9c2;border-radius:11px;padding:10px 14px;
  font-size:13px;color:var(--orange-deep);margin:16px 0}
.empty{color:var(--gray);font-size:14.5px;padding:22px 0}

details.counts{margin-top:34px}
details.counts summary{cursor:pointer;color:var(--navy);font-weight:600;font-size:14px;
  padding:9px 0;border-top:1px solid var(--line);list-style:none}
details.counts summary::-webkit-details-marker{display:none}
details.counts summary::before{content:"▸ ";color:var(--orange)}
details.counts[open] summary::before{content:"▾ "}
.tbl-scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff;border:1px solid var(--line);
  border-radius:10px;overflow:hidden;margin-top:8px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line-soft);vertical-align:top}
th{background:#f0f5f9;color:var(--navy);font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:none}
td.num{white-space:nowrap;font-variant-numeric:tabular-nums}
.err{color:#b4340a;font-weight:600}

.foot{margin-top:44px;text-align:center;color:var(--slate-soft);font-size:13px}

@media(max-width:640px){
  .overview{grid-template-columns:1fr}
  .report-head h1{font-size:24px}
  .navrow select{max-width:none}
}
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <span class="brand">Précon <span>Regulatory Monitor</span></span>
  </div>
</header>
<main class="wrap">
  <div class="overview" id="overview"></div>
  <div class="navrow">
    <button class="arrow" id="olderBtn" aria-label="Oudere rapportage" title="Ouder">&#9664;</button>
    <select id="runSelect" aria-label="Kies rapportage"></select>
    <button class="arrow" id="newerBtn" aria-label="Nieuwere rapportage" title="Nieuwer">&#9654;</button>
  </div>
  <div id="report"></div>
  <div class="foot" id="foot"></div>
</main>
<script src="runs.js"></script>
<script src="app.js"></script>
</body>
</html>
"""

APP_JS = r"""(function () {
  "use strict";
  var R = window.RUNS || { daily: [], weekly: [], notes: {}, generated_at: null };
  var MON = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso + "T00:00:00");
    return d.getDate() + " " + MON[d.getMonth()] + " " + d.getFullYear();
  }
  function fmtRange(a, b) {
    if (!a || a === b) return fmtDate(b);
    return fmtDate(a) + " – " + fmtDate(b);
  }
  function fmtStamp(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleString("nl-NL", {
        day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
        timeZone: "Europe/Amsterdam",
      });
    } catch (e) { return iso; }
  }

  function listFor(mode) { return mode === "week" ? R.weekly : R.daily; }

  function parseHash() {
    var h = location.hash.replace(/^#\/?/, "");
    var parts = h.split("/");
    var mode = parts[0] === "week" ? "week" : "dag";
    return { mode: mode, id: parts[1] || null };
  }
  function currentRun(state) {
    var list = listFor(state.mode);
    if (!list.length) return null;
    if (state.id) {
      for (var i = 0; i < list.length; i++) if (list[i].id === state.id) return list[i];
    }
    return list[0];
  }

  function card(p, ad) {
    var topic = (p.topic || "").replace("[EXP] ", "");
    return (
      '<div class="card' + (ad ? " ad" : "") + '">' +
        '<div class="card-top"><span class="pill">' + esc(topic) + "</span>" +
        '<span class="date">' + esc(fmtDate(p.pub_date)) + "</span></div>" +
        '<div class="title">' + esc(p.title) + "</div>" +
        '<div class="src">' + esc(p.source || "") + "</div>" +
        '<a class="go" href="' + esc(p.url) + '" target="_blank" rel="noopener">Bekijk publicatie ↗</a>' +
      "</div>"
    );
  }

  function countsTable(counts, notes) {
    var rows = counts.map(function (c) {
      var ratio;
      if (c.api_error) ratio = '<span class="err">API fout</span>';
      else if (!c.total && !c.relevant) ratio = "—";
      else ratio = c.relevant + "/" + c.total;
      var note = notes[c.label] || c.note || "";
      return "<tr><td>" + esc(c.label) + '</td><td class="num">' + esc(c.date_str) +
        '</td><td class="num">' + ratio + "</td><td>" + esc(note) + "</td></tr>";
    }).join("");
    return '<div class="tbl-scroll"><table><thead><tr><th>Bron</th><th>Periode</th>' +
      "<th>Rel./tot.</th><th>Opmerking</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function renderReport(mode, run) {
    var notes = R.notes || {};
    var pubs = (run.publications || []).slice().sort(function (a, b) {
      return (b.pub_date || "").localeCompare(a.pub_date || "");
    });
    var ad = run.antidumping || [];
    var kind = mode === "week" ? "Weekrapportage" : "Dagelijkse rapportage";
    var runLabels = {};
    (run.counts || []).forEach(function (c) { runLabels[c.label] = 1; });
    var manual = Object.keys(notes).filter(function (k) { return notes[k] && runLabels[k]; });

    var h = "";
    h += '<div class="report-head"><h1>' + esc(kind) + "</h1>" +
      '<div class="report-sub">' + esc(run.label) + " &middot; periode " +
      esc(fmtRange(run.from, run.to)) + " &middot; bijgewerkt " + esc(fmtStamp(run.generated_at)) + "</div></div>";

    h += '<div class="statline"><span class="stat">' + pubs.length + "</span> relevante publicatie" +
      (pubs.length === 1 ? "" : "s");
    if (ad.length) h += ' &middot; <span class="stat-ad">' + ad.length + "</span> anti-dumping signalering" + (ad.length === 1 ? "" : "en");
    h += "</div>";

    if (manual.length) {
      h += '<div class="warn">&#9888; Handmatig checken (bron niet automatiseerbaar): ' + esc(manual.join(", ")) + "</div>";
    }

    h += '<div class="section-title">Relevante publicaties</div>';
    h += pubs.length
      ? pubs.map(function (p) { return card(p, false); }).join("")
      : '<div class="empty">Geen relevante publicaties gevonden in deze periode.</div>';

    if (ad.length) {
      h += '<div class="section-title">Anti-dumping signaleringen</div>';
      h += ad.map(function (p) { return card(p, true); }).join("");
    }

    h += '<details class="counts"><summary>Tellingen per bron (' + (run.counts || []).length + ")</summary>" +
      countsTable(run.counts || [], notes) + "</details>";
    return h;
  }

  function renderOverview(activeMode) {
    var box = document.getElementById("overview");
    var tiles = [
      { mode: "dag", label: "Laatste dag", run: R.daily[0] },
      { mode: "week", label: "Laatste week", run: R.weekly[0] },
    ];
    box.innerHTML = tiles.map(function (t) {
      var n = t.run ? (t.run.publications || []).length : 0;
      var when = t.run ? (t.mode === "week" ? t.run.label : fmtDate(t.run.to)) : "—";
      return '<button class="ov-tile' + (t.mode === activeMode ? " active" : "") + '" data-mode="' + t.mode + '">' +
        '<span class="ov-label">' + t.label + "</span>" +
        '<span class="ov-date">' + esc(when) + "</span>" +
        '<span class="ov-count">' + n + " <small>relevant</small></span>" +
        "</button>";
    }).join("");
  }

  function render() {
    var state = parseHash();
    var list = listFor(state.mode);
    var run = currentRun(state);

    renderOverview(state.mode);

    var sel = document.getElementById("runSelect");
    sel.innerHTML = list.map(function (r) {
      return '<option value="' + esc(r.id) + '">' + esc(r.label) + "</option>";
    }).join("");
    var idx = run ? list.map(function (r) { return r.id; }).indexOf(run.id) : -1;
    if (run) sel.value = run.id;
    document.getElementById("olderBtn").disabled = !(idx >= 0 && idx < list.length - 1);
    document.getElementById("newerBtn").disabled = !(idx > 0);

    document.getElementById("report").innerHTML = run
      ? renderReport(state.mode, run)
      : '<div class="empty">Nog geen ' + (state.mode === "week" ? "week" : "dag") + "rapportages gegenereerd.</div>";

    document.getElementById("foot").textContent =
      R.generated_at ? "Site bijgewerkt: " + fmtStamp(R.generated_at) + " · Précon" : "Précon";
  }

  function step(delta) {
    var state = parseHash();
    var list = listFor(state.mode);
    var run = currentRun(state);
    if (!run) return;
    var i = list.map(function (r) { return r.id; }).indexOf(run.id);
    var j = i + delta;
    if (j < 0 || j >= list.length) return;
    location.hash = state.mode + "/" + list[j].id;
  }

  document.getElementById("overview").addEventListener("click", function (e) {
    var btn = e.target.closest(".ov-tile");
    if (btn) location.hash = btn.dataset.mode;
  });
  document.getElementById("runSelect").addEventListener("change", function (e) {
    location.hash = parseHash().mode + "/" + e.target.value;
  });
  document.getElementById("olderBtn").addEventListener("click", function () { step(1); });
  document.getElementById("newerBtn").addEventListener("click", function () { step(-1); });
  window.addEventListener("hashchange", render);
  render();
})();
"""


def build_site() -> None:
    config = load_config()
    daily = load_runs("daily")
    weekly = load_runs("weekly")

    stamps = [r["generated_at"] for r in daily + weekly if r.get("generated_at")]
    generated_at = max(stamps) if stamps else datetime.now(timezone.utc).isoformat(timespec="seconds")

    payload = {
        "generated_at": generated_at,
        "notes": config.manual_check_notes,
        "daily": daily,
        "weekly": weekly,
    }

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (PUBLIC_DIR / "runs.js").write_text(
        "window.RUNS = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (PUBLIC_DIR / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (PUBLIC_DIR / "app.js").write_text(APP_JS, encoding="utf-8")

    print(f"  Site gebouwd: {len(daily)} dag + {len(weekly)} week rapportages -> {PUBLIC_DIR}")


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

    sub.add_parser("rebuild", help="Herbouw alleen de site uit data/, zonder bronnen te bevragen")

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

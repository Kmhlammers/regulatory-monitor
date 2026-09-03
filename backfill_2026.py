"""One-off: run the pipeline for every day/week that appears in the
`historyData/Law updates Non-food 2026.xlsx` monitoring workbook, so the same
periods show up on the published site — generated fresh through our own parser,
not copied from the Excel.

Resumable: skips any period already present in data/{daily,weekly}/. Each run is
saved immediately. Run `python build_site.py rebuild` afterwards to regenerate
the site from data/.

    python backfill_2026.py            # do all missing daily + weekly
    python backfill_2026.py --only daily
    python backfill_2026.py --only weekly
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from regulatory_monitor.config import load_config  # noqa: E402
from regulatory_monitor.matching import RelevanceMatcher  # noqa: E402
from build_site import DATA_DIR, run_daily, run_weekly, save_run  # noqa: E402
from regulatory_monitor.cli import week_to_dates  # noqa: E402

XLSX = ROOT / "historyData" / "Law updates Non-food 2026.xlsx"
LOG = ROOT / "backfill_2026.log"
PAUSE_BETWEEN_RUNS = 1.0  # be gentle on the government APIs


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def daily_targets() -> list[date]:
    df = pd.read_excel(XLSX, sheet_name="Daily check", header=None)
    return sorted({v.date() for v in df.iloc[:, 1].tolist() if hasattr(v, "year") and v.year == 2026})


def weekly_targets() -> list[int]:
    df = pd.read_excel(XLSX, sheet_name="Weekly check", header=None)
    weeks = {
        int(w)
        for w in df.iloc[:, 0].tolist()
        if isinstance(w, (int, float)) and not pd.isna(w) and 1 <= w <= 53
    }
    return sorted(weeks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["daily", "weekly"])
    args = ap.parse_args()

    matcher = RelevanceMatcher(load_config())

    days = daily_targets()
    weeks = weekly_targets()
    log(f"Excel: {len(days)} dagen ({days[0]} … {days[-1]}), weken {weeks[0]}–{weeks[-1]}")

    done = 0
    skipped = 0
    failed: list[str] = []

    if args.only != "weekly":
        for i, d in enumerate(days, 1):
            out = DATA_DIR / "daily" / f"{d.isoformat()}.json"
            if out.exists():
                skipped += 1
                continue
            log(f"[dag {i}/{len(days)}] {d.isoformat()} …")
            try:
                run = run_daily(d, d, matcher)
                path = save_run(run)
                n = len(run["publications"])
                errs = [c["label"] for c in run["counts"] if c["api_error"]]
                log(f"    -> {n} relevant, {len(errs)} bronfout{' (' + ', '.join(errs) + ')' if errs else ''}  {path.name}")
                done += 1
            except Exception:  # noqa: BLE001
                failed.append(f"dag {d.isoformat()}")
                log(f"    !! FOUT\n{traceback.format_exc()}")
            time.sleep(PAUSE_BETWEEN_RUNS)

    if args.only != "daily":
        for i, w in enumerate(weeks, 1):
            rid = f"2026-W{w:02d}"
            out = DATA_DIR / "weekly" / f"{rid}.json"
            if out.exists():
                skipped += 1
                continue
            frm, to = week_to_dates(w, 2026)
            log(f"[week {i}/{len(weeks)}] {rid} ({frm} t/m {to}) …")
            try:
                run = run_weekly(w, 2026, matcher)
                path = save_run(run)
                n = len(run["publications"])
                errs = [c["label"] for c in run["counts"] if c["api_error"]]
                log(f"    -> {n} relevant, {len(errs)} bronfout{' (' + ', '.join(errs) + ')' if errs else ''}  {path.name}")
                done += 1
            except Exception:  # noqa: BLE001
                failed.append(f"week {rid}")
                log(f"    !! FOUT\n{traceback.format_exc()}")
            time.sleep(PAUSE_BETWEEN_RUNS)

    log(f"KLAAR. {done} nieuw, {skipped} overgeslagen (bestond al), {len(failed)} mislukt.")
    if failed:
        log("Mislukt: " + ", ".join(failed))


if __name__ == "__main__":
    main()

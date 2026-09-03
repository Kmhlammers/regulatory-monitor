"""Streamlit dashboard for the Regulatory Monitor, rebuilt from the original app.py
(same two-tab layout: Dagelijkse rapportage / Weekrapportage)."""
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from regulatory_monitor.cli import week_to_dates
from regulatory_monitor.config import load_config
from regulatory_monitor.matching import RelevanceMatcher
from regulatory_monitor.pipeline import DAILY_SOURCES, EXPERIMENTAL_WEEKLY_SOURCES, WEEKLY_SOURCES, deduplicate, run_sources

st.set_page_config(page_title="Non-food Regulatory Monitor | Précon", layout="wide", initial_sidebar_state="collapsed")

GREEN = "#2D5016"
GREEN_HOVER = "#3a6a1c"
GREEN_LIGHT = "#eef3e8"
GREY_LIGHT = "#f7f7f7"
GREY_BORDER = "#e0e0e0"
TEXT = "#1a1a1a"
TEXT_MUTED = "#666666"

st.markdown(
    f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; color: {TEXT}; }}
  .pc-header {{ background: {GREEN}; padding: 1.4rem 2rem 1.2rem; margin: -4rem -4rem 2rem -4rem;
                display: flex; align-items: center; gap: 1.2rem; }}
  .pc-header-text h1 {{ color: #fff; font-size: 1.25rem; font-weight: 600; margin: 0 0 0.15rem; }}
  .pc-header-text p {{ color: rgba(255,255,255,.65); font-size: 0.8rem; margin: 0; }}
  .stTabs [data-baseweb="tab-list"] {{ gap: 4px; background: {GREY_LIGHT}; border-radius: 6px;
                                        padding: 4px; border: 1px solid {GREY_BORDER}; }}
  .stTabs [data-baseweb="tab"] {{ border-radius: 4px; color: {TEXT_MUTED}; font-weight: 500;
                                   font-size: 0.9rem; padding: 0.45rem 1.4rem; border: none; }}
  .stTabs [aria-selected="true"] {{ background: {GREEN} !important; color: #fff !important; }}
  .stTabs [data-baseweb="tab-panel"] {{ padding-top: 1.5rem; }}
  .stButton > button {{ background: {GREEN}; color: #fff; border: none; border-radius: 4px;
                         padding: 0.5rem 1.4rem; font-weight: 500; font-size: 0.9rem; width: 100%;
                         transition: background .15s; }}
  .stButton > button:hover {{ background: {GREEN_HOVER} !important; color: #fff !important; }}
  .stButton > button:focus {{ box-shadow: 0 0 0 3px rgba(45,80,22,.25); }}
  .pc-section {{ color: {GREEN}; font-weight: 600; font-size: 0.95rem;
                 border-bottom: 2px solid {GREEN}; padding-bottom: 0.35rem; margin: 1.5rem 0 1rem; }}
  .pc-card {{ background: #fff; border: 1px solid {GREY_BORDER}; border-left: 4px solid {GREEN};
              border-radius: 4px; padding: 0.9rem 1.1rem; margin-bottom: 0.6rem; }}
  .pc-card-topic {{ font-weight: 600; font-size: 0.9rem; color: {GREEN}; }}
  .pc-card-date {{ color: {TEXT_MUTED}; font-size: 0.8rem; }}
  .pc-card-title {{ color: {TEXT}; font-size: 0.88rem; margin: 0.3rem 0 0.4rem; line-height: 1.4; }}
  .pc-card-link {{ color: {GREEN}; font-size: 0.82rem; text-decoration: none; }}
  .pc-card-link:hover {{ text-decoration: underline; }}
  .pc-warning {{ background: #fffbea; border: 1px solid #f0d070; border-radius: 4px;
                 padding: 0.7rem 1rem; font-size: 0.83rem; margin-top: 1rem; color: #6b5300; }}
  .pc-empty {{ color: {TEXT_MUTED}; font-size: 0.9rem; padding: 2rem 0; }}
  .pc-divider {{ border: none; border-top: 1px solid {GREY_BORDER}; margin: 1.5rem 0; }}
  #MainMenu, footer, header {{ visibility: hidden; }}
  .block-container {{ padding-top: 4.5rem !important; }}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="pc-header"><div class="pc-header-text"><h1>Non-food Regulatory Monitor</h1></div></div>',
    unsafe_allow_html=True,
)


@st.cache_resource
def get_matcher():
    config = load_config()
    return config, RelevanceMatcher(config)


CONFIG, MATCHER = get_matcher()


def run_check(mode: str, from_date: date, to_date: date, experimental: bool = False):
    if mode == "daily":
        pubs, counts = run_sources(DAILY_SOURCES, from_date, to_date, MATCHER)
    else:
        sources = WEEKLY_SOURCES + (list(EXPERIMENTAL_WEEKLY_SOURCES) if experimental else [])
        exp_labels = set(EXPERIMENTAL_WEEKLY_SOURCES) if experimental else set()
        pubs, counts = run_sources(sources, from_date, to_date, MATCHER, experimental_labels=exp_labels)
    unique = deduplicate(pubs)
    antidumping_hits = [p for p in unique if MATCHER.is_antidumping(p.title)]
    return unique, counts, antidumping_hits


def counts_to_df(counts) -> pd.DataFrame:
    rows = []
    for c in counts:
        if c.api_error:
            ratio = "⚠ API fout"
        elif c.total == 0 and c.relevant == 0:
            ratio = "—"
        else:
            ratio = f"{c.relevant}/{c.total}"
        note = CONFIG.manual_check_notes.get(c.label, c.note)
        rows.append({"Bron": c.label, "Periode": c.date_str, "Verhouding": ratio, "Opmerking": note})
    return pd.DataFrame(rows)


def pubs_to_csv_bytes(pubs) -> bytes:
    buf = io.StringIO()
    buf.write("Week;Onderwerp;Titel;Link;Datum\n")
    for p in pubs:
        d = p.pub_date.strftime("%d-%m-%Y") if p.pub_date else ""
        buf.write(f"{p.week};{p.topic};{p.title};{p.url};{d}\n")
    return buf.getvalue().encode("utf-8-sig")


def show_pub_card(p, color: str = GREEN) -> None:
    datum = p.pub_date.strftime("%d-%m-%Y") if p.pub_date else "—"
    titel = p.title if len(p.title) <= 160 else p.title[:157] + "…"
    topic = p.topic.replace("[EXP] ", "")
    st.markdown(
        f"""
    <div class="pc-card" style="border-left-color:{color};">
      <span class="pc-card-topic" style="color:{color};">{topic}</span>
      <span class="pc-card-date"> &nbsp;·&nbsp; {datum}</span>
      <div class="pc-card-title">{titel}</div>
      <a class="pc-card-link" href="{p.url}" target="_blank">↗ Bekijk publicatie</a>
    </div>""",
        unsafe_allow_html=True,
    )


def show_results(pubs, counts, checked_range: str, antidumping_hits) -> None:
    st.markdown('<div class="pc-section">Tellingen per bron</div>', unsafe_allow_html=True)
    st.dataframe(counts_to_df(counts), use_container_width=True, hide_index=True)

    manual_only = [label for label, note in CONFIG.manual_check_notes.items() if note]
    if manual_only:
        st.markdown(
            f'<div class="pc-warning">⚠ Handmatig checken: {", ".join(manual_only)}</div>',
            unsafe_allow_html=True,
        )

    st.markdown(f'<div class="pc-section">Relevante publicaties ({len(pubs)})</div>', unsafe_allow_html=True)
    if not pubs:
        st.markdown('<div class="pc-empty">Geen relevante publicaties gevonden.</div>', unsafe_allow_html=True)
    else:
        for p in sorted(pubs, key=lambda p: p.pub_date or date.min, reverse=True):
            show_pub_card(p)
        st.download_button("⬇ Download CSV", data=pubs_to_csv_bytes(pubs), file_name="regulatory_results.csv", mime="text/csv")

    if antidumping_hits:
        st.markdown(f'<div class="pc-section">Anti-dumping signaleringen ({len(antidumping_hits)})</div>', unsafe_allow_html=True)
        for p in antidumping_hits:
            show_pub_card(p, color="#b5651d")


tab_dag, tab_week = st.tabs(["📅  Dagelijkse rapportage", "📆  Weekrapportage"])

with tab_dag:
    col_ctrl, col_res = st.columns([1, 3], gap="large")
    with col_ctrl:
        st.markdown("**Datum**")
        dag = st.date_input("Datum", value=date.today() - timedelta(days=1), key="d_date", label_visibility="collapsed")
        exp_dag = st.checkbox("Experimentele bronnen", key="d_exp")
        run_dag = st.button("▶  Start dagelijkse check", key="d_run")
    with col_res:
        if run_dag:
            with st.spinner("Bronnen worden gecontroleerd…"):
                pubs, counts, antidumping_hits = run_check("daily", dag, dag, experimental=exp_dag)
            show_results(pubs, counts, dag.isoformat(), antidumping_hits)
        else:
            st.markdown('<div class="pc-empty">Kies een datum en klik op "Start dagelijkse check".</div>', unsafe_allow_html=True)

with tab_week:
    col_ctrl, col_res = st.columns([1, 3], gap="large")
    with col_ctrl:
        today = date.today()
        cur_week = today.isocalendar()[1]
        cur_year = today.year
        st.markdown("**Week**")
        wk = st.number_input("Week", min_value=1, max_value=53, value=cur_week, key="w_week", label_visibility="collapsed")
        st.markdown("**Jaar**")
        yr = st.number_input("Jaar", min_value=2020, max_value=2035, value=cur_year, key="w_year", label_visibility="collapsed")
        wfrom, wto = week_to_dates(int(wk), int(yr))
        st.caption(f"{wfrom.strftime('%d-%m-%Y')} t/m {wto.strftime('%d-%m-%Y')}")
        exp_week = st.checkbox("Experimentele bronnen", key="w_exp")
        run_week = st.button("▶  Start weekrapportage", key="w_run")
    with col_res:
        if run_week:
            with st.spinner("Bronnen worden gecontroleerd…"):
                pubs, counts, antidumping_hits = run_check("weekly", wfrom, wto, experimental=exp_week)
            show_results(pubs, counts, f"week {wk} ({yr})", antidumping_hits)
        else:
            st.markdown('<div class="pc-empty">Kies een week en klik op "Start weekrapportage".</div>', unsafe_allow_html=True)

"""Loads nonfood_monitor_config.json and exposes it as typed Python structures."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "nonfood_monitor_config.json"


@dataclass
class ExclusionPair:
    term1: str
    term2: str


@dataclass
class MonitorConfig:
    topic_keywords: dict[str, list[str]]
    topic_instruments: dict[str, list[str]]
    title_exclusion_pairs: list[ExclusionPair]
    title_exclusion_phrases: list[str]
    antidumping_keywords: list[str]
    manual_check_notes: dict[str, str]
    bronnen: dict[str, list[str]]
    bron_details: dict[str, dict]

    @property
    def daily_sources(self) -> list[str]:
        return self.bronnen.get("dagelijks", [])

    @property
    def weekly_sources(self) -> list[str]:
        return self.bronnen.get("wekelijks", [])

    @property
    def experimental_weekly_sources(self) -> list[str]:
        return self.bronnen.get("experimenteel_wekelijks", [])


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> MonitorConfig:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    pairs = [
        ExclusionPair(term1=p["term1"], term2=p["term2"])
        for p in raw.get("title_exclusion_pairs", [])
    ]

    return MonitorConfig(
        topic_keywords=raw.get("topic_keywords", {}),
        topic_instruments=raw.get("topic_instruments", {}),
        title_exclusion_pairs=pairs,
        title_exclusion_phrases=raw.get("title_exclusion_phrases", []),
        antidumping_keywords=raw.get("antidumping_keywords", []),
        manual_check_notes=raw.get("manual_check_notes", {}),
        bronnen=raw.get("bronnen", {}),
        bron_details=raw.get("bron_details", {}),
    )

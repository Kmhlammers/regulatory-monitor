"""Data models for the Regulatory Monitor pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Publication:
    """A single relevant publication found in a source."""

    source: str
    topic: str
    title: str
    url: str
    pub_date: Optional[date] = None
    week: str = ""


@dataclass
class SourceCount:
    """Relevant/total tally for one source over one date range, for the summary tab."""

    label: str
    date_str: str
    relevant: int = 0
    total: int = 0
    api_error: bool = False
    note: str = ""


@dataclass
class FetchResult:
    publications: list[Publication] = field(default_factory=list)
    counts: list[SourceCount] = field(default_factory=list)

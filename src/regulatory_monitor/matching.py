"""Title-relevance matching — a direct port of ``is_relevant()`` from the real
regulatory_monitor.py (confirmed against the colleague's actual source, not
reconstructed).

Confirmed real behaviour: every keyword gets only a *leading* word boundary
(``\\b<keyword>``, case-insensitive), so plurals/conjugations like 'cosmetic' ->
'cosmetics' still match. ALL_CAPS acronyms get a boundary on both sides and are
case-sensitive. This is deliberate, not a bug — see the docstring/comment in her
source. Digging into her actual output (`regulatory_results.csv`,
`experimental_results_week18_2026.csv`) turned up no evidence that this leading-
boundary design is what's driving false positives; the confirmed false-positive
sources are two real bugs elsewhere (see sources/html_scrape.py's fetch_sccs and
fetch_fod_vg docstrings) — not this matching rule. Default behaviour therefore
matches the original exactly. A stricter, both-sided-boundary mode is still
available via ``strict_boundaries=True`` for anyone who wants to experiment with
it against real data, but it is opt-in, not the default.

Two additions on top of the original, both aimed at recall (see the pipeline-vs-Excel
validation):

1. Citation normalisation. EU acts cite each other as ``Regulation (EU) 2024/1781``
   or ``Regulation (EC) No 1907/2006``; the ``(EU)`` / ``(EC) No`` infix defeats
   any ``regulation 2024/1781``-style keyword. ``match()`` collapses that infix on
   a working copy of the title before matching. (The originally-shipped config
   worked around this one number at a time — e.g. a bare ``10/2011`` keyword next
   to ``regulation 10/2011``.)
2. Referenced-instrument matching. ``topic_instruments`` in the config maps a topic
   to the framework regulation/directive numbers that define it. If the title names
   one of those instruments (``2009/48`` → Speelgoed, ``2024/1781`` → ESPR, …) the
   publication is relevant even when no topic keyword hits — this catches
   implementing/delegated/amending acts by construction. Empty ``topic_instruments``
   → this stage is a no-op and behaviour is identical to before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import MonitorConfig

# "Regulation (EU) No 10/2011" / "Directive (EU) 2026/470" / "Verordening (EU) 2024/1157"
# -> "Regulation 10/2011" / "Directive 2026/470" / "Verordening 2024/1157"
_CITATION_INFIX_RE = re.compile(
    r"\b(regulation|directive|verordening|richtlijn)s?\.?\s*\(\s*E[UC]\s*\)\s*(?:no\.?\s+|nr\.?\s+)?",
    re.IGNORECASE,
)

# Legal instrument numbers: 2024/1781, 10/2011, 1907/2006, 84/500 …
_INSTRUMENT_RE = re.compile(r"\b\d{1,4}/\d{1,4}\b")


def _normalise_citations(title: str) -> str:
    return _CITATION_INFIX_RE.sub(lambda m: f"{m.group(1)} ", title)


@dataclass
class MatchResult:
    relevant: bool
    topic: str | None = None
    matched_keyword: str | None = None
    excluded_by: str | None = None


def _keyword_pattern(keyword: str, strict_boundaries: bool) -> re.Pattern:
    escaped = re.escape(keyword)
    is_acronym = keyword.isupper() and keyword.isalpha() and len(keyword) > 1
    if is_acronym:
        return re.compile(rf"\b{escaped}\b")
    trailing = r"\b" if strict_boundaries else ""
    return re.compile(rf"\b{escaped}{trailing}", re.IGNORECASE)


class RelevanceMatcher:
    """Reusable matcher: compiles all keyword/exclusion patterns once."""

    def __init__(self, config: MonitorConfig, strict_boundaries: bool = False):
        self.config = config
        self.strict_boundaries = strict_boundaries
        self._topic_patterns: dict[str, list[tuple[str, re.Pattern]]] = {
            topic: [(kw, _keyword_pattern(kw, strict_boundaries)) for kw in keywords]
            for topic, keywords in config.topic_keywords.items()
        }
        self._topic_instruments: dict[str, set[str]] = {
            topic: {str(n).strip() for n in numbers}
            for topic, numbers in config.topic_instruments.items()
        }
        self._exclusion_pair_patterns = [
            (pair.term1, pair.term2,
             re.compile(re.escape(pair.term1), re.IGNORECASE),
             re.compile(re.escape(pair.term2), re.IGNORECASE))
            for pair in config.title_exclusion_pairs
        ]
        self._exclusion_phrase_patterns = [
            (phrase, re.compile(re.escape(phrase), re.IGNORECASE))
            for phrase in config.title_exclusion_phrases
        ]
        self._antidumping_patterns = [
            re.compile(re.escape(kw), re.IGNORECASE) for kw in config.antidumping_keywords
        ]

    def match(self, title: str) -> MatchResult:
        norm = _normalise_citations(title)

        for term1, term2, p1, p2 in self._exclusion_pair_patterns:
            if p1.search(norm) and p2.search(norm):
                return MatchResult(relevant=False, excluded_by=f"pair:{term1}+{term2}")

        for phrase, pattern in self._exclusion_phrase_patterns:
            if pattern.search(norm):
                return MatchResult(relevant=False, excluded_by=f"phrase:{phrase}")

        if self._topic_instruments:
            numbers = set(_INSTRUMENT_RE.findall(norm))
            if numbers:
                for topic, instruments in self._topic_instruments.items():
                    hit = numbers & instruments
                    if hit:
                        return MatchResult(
                            relevant=True, topic=topic,
                            matched_keyword=f"instrument {sorted(hit)[0]}",
                        )

        for topic, patterns in self._topic_patterns.items():
            for keyword, pattern in patterns:
                if pattern.search(norm):
                    return MatchResult(relevant=True, topic=topic, matched_keyword=keyword)

        return MatchResult(relevant=False)

    def is_antidumping(self, title: str) -> bool:
        return any(p.search(title) for p in self._antidumping_patterns)

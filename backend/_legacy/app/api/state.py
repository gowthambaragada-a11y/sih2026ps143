"""Shared API state: cached analyses + model version registry.

Running an analysis takes ~10s (CPU), so results are cached per event_id
(plus analysis parameters).  The dashboard usually fetches one event and
then drills into it via stage-specific endpoints.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional

from ..services.pipeline import AnalysisResult, run_analysis

_cache: Dict[str, AnalysisResult] = {}
_lock = threading.Lock()


def get_analysis(event_id: str, *, refresh: bool = False, seed: int = 7,
                 n_members: int = 16) -> AnalysisResult:
    """Return a cached analysis for an event, running it if needed."""
    key = event_id
    with _lock:
        if not refresh and key in _cache:
            return _cache[key]
    result = run_analysis(event_id=event_id, seed=seed, n_members=n_members)
    with _lock:
        _cache[key] = result
    return result


def list_events() -> list:
    with _lock:
        return sorted(_cache.keys())


def purge_events() -> None:
    with _lock:
        _cache.clear()

"""Event-level evaluation harness for OILTRACE-AI.

Runs the full pipeline over a matrix of synthetic reference events and scores
each stage against the known ground truth provided by :class:`DemoScenario`:

  * Detection  - distance between the detected slick centroid and the true
                 (drift-simulated) slick centroid.
  * Origin     - distance from the best origin hypothesis to the true release
                 point, and release-time error vs the true release time.
  * Attribution- rank of the true (synthetic reference) vessel, top-k hit
                 rate, and score margin to the next-ranked vessel.

Outputs a compact summary table, plus optional persisted JSON of per-event
metrics so regressions can be compared across runs.

Stage metrics are strictly separated: a metric never mixes information from a
later stage (e.g. attribution numbers are computed only from ranked vessels).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import demo as demo_mod
from . import pipeline
from ..core.geo import haversine_km

EVAL_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "evaluation"


# ---------------------------------------------------------------------------
# Per-event metrics
# ---------------------------------------------------------------------------
def evaluate_event(event_id: str, seed: int, n_members: int,
                   use_pretrained: bool = True) -> dict:
    """Run the pipeline for one synthetic reference event and score it."""

    demo = demo_mod.build_demo_scenario(seed=seed, event_id=event_id)
    res = pipeline.run_analysis(
        event_id=event_id, seed=seed, n_members=n_members,
        use_pretrained=use_pretrained,
    )

    # --- detection: centroid vs known synthetic slick centroid ---
    det_c = res.detection.centroid
    truth_slick = demo.slick_centroid_geo
    det_err_km = haversine_km(det_c.lat, det_c.lon, truth_slick[0], truth_slick[1])

    # --- origin: distance to true release, release-time error ---
    origin = res.origin
    true_origin = demo.origin_geo
    cands = origin.candidates
    origin_dists_km = [
        haversine_km(c.lat, c.lon, true_origin[0], true_origin[1]) for c in cands
    ]
    origin_best_km = float(np.min(origin_dists_km)) if origin_dists_km else float("nan")
    origin_top_km = (
        haversine_km(cands[0].lat, cands[0].lon, true_origin[0], true_origin[1])
        if cands else float("nan")
    )
    rel_err_h = (
        abs(cands[0].release_time - demo.origin_release_time_s) / 3600.0
        if cands else float("nan")
    )
    origin_prob_top = cands[0].probability if cands else float("nan")

    # --- attribution: rank/margin of the true vessel ---
    ranked = res.attribution.ranked_vessels
    truth_v = demo.truth_mmsi
    order = [v.mmsi for v in ranked]
    rank = (order.index(truth_v) + 1) if truth_v in order else len(order) + 1
    top_k_hit = {1: rank <= 1, 2: rank <= 2, 3: rank <= 3}
    scores = {v.mmsi: v.scores.overall for v in ranked}
    truth_score = scores.get(truth_v, float("nan"))
    others = [v.scores.overall for v in ranked if v.mmsi != truth_v]
    best_other = float(max(others)) if others else float("nan")
    margin = (truth_score - best_other) if truth_v in scores and others else float("nan")

    return {
        "event_id": event_id,
        "seed": seed,
        "n_members": n_members,
        "detection_error_km": round(det_err_km, 3),
        "origin_best_km": round(origin_best_km, 3),
        "origin_top_km": round(origin_top_km, 3),
        "release_time_error_h": round(float(rel_err_h), 2),
        "origin_prob_top": round(float(origin_prob_top), 4),
        "truth_rank": rank,
        "rank1_hit": top_k_hit[1],
        "rank2_hit": top_k_hit[2],
        "rank3_hit": top_k_hit[3],
        "margin": round(float(margin), 2),
        "truth_score": round(float(truth_score), 2),
        "n_vessels": len(ranked),
    }


# ---------------------------------------------------------------------------
# Multi-event sweep + aggregation
# ---------------------------------------------------------------------------
def run_evaluation(
    seeds: Optional[List[int]] = None,
    n_members_list: Optional[List[int]] = None,
    event_prefix: str = "SIH-2026-SPILL",
    use_pretrained: bool = True,
    persist: bool = True,
) -> Tuple[list, dict]:
    """Run the pipeline over a matrix of seeds x ensemble sizes and aggregate."""

    seeds = seeds or [1, 3, 5, 7, 11]
    n_members_list = n_members_list or [12, 16, 20]

    rows: list = []
    for seed in seeds:
        for n_members in n_members_list:
            event_id = f"{event_prefix}-{seed:02d}-n{n_members}"
            m = evaluate_event(event_id, seed, n_members, use_pretrained)
            rows.append(m)
            print(
                f"seed={seed:>2} n={n_members:>2} | det={m['detection_error_km']:6.2f}km "
                f"origin_top={m['origin_top_km']:6.2f}km rel_err={m['release_time_error_h']:5.1f}h "
                f"rank={m['truth_rank']}/{m['n_vessels']} margin={m['margin']:+.1f}"
            )

    agg = _aggregate(rows)

    if persist:
        out = EVAL_DIR / f"eval_{len(rows)}events.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"rows": rows, "aggregate": agg}, indent=2))
        print(f"\npersisted -> {out}")

    return rows, agg


def _aggregate(rows: list) -> dict:
    def m(key):
        vals = [r[key] for r in rows if not isinstance(r.get(key), bool)]
        return round(float(np.mean(vals)), 3), round(float(np.std(vals)), 3)

    def hit(key):
        vals = [r[key] for r in rows]
        return round(100.0 * sum(vals) / len(vals), 1)

    return {
        "detection_error_km": m("detection_error_km"),
        "origin_best_km": m("origin_best_km"),
        "origin_top_km": m("origin_top_km"),
        "release_time_error_h": m("release_time_error_h"),
        "median_truth_rank": float(np.median([r["truth_rank"] for r in rows])),
        "rank1_hit_rate_%": hit("rank1_hit"),
        "rank2_hit_rate_%": hit("rank2_hit"),
        "rank3_hit_rate_%": hit("rank3_hit"),
        "mean_margin": round(float(np.mean([r["margin"] for r in rows])), 2),
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="OILTRACE-AI event evaluation sweep")
    p.add_argument("--seeds", type=int, nargs="*", default=[1, 3, 5, 7, 11])
    p.add_argument("--n-members", type=int, nargs="*", default=[12, 16, 20])
    p.add_argument("--no-persist", action="store_true")
    args = p.parse_args()
    _, agg = run_evaluation(
        seeds=args.seeds, n_members_list=args.n_members,
        persist=not args.no_persist,
    )
    print("\n=== aggregate ===")
    print(json.dumps(agg, indent=2))